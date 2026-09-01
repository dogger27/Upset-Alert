import ActivityKit
import SwiftUI
import WidgetKit

// The Lock Screen itself.
//
// Design rule for everything below: SHOW THE PICK, NOT JUST THE SCORE. A
// scores app can render a scoreboard; the reason this one is worth a Lock
// Screen is that it knows which player the viewer chose, so the person they
// picked is the one that is highlighted and the one the tick or cross hangs
// off. Strip that out and this is a worse version of a dozen other apps.

private let ink = Color(red: 0.93, green: 0.95, blue: 0.94)
private let muted = Color(red: 0.58, green: 0.64, blue: 0.62)
private let accent = Color(red: 0.79, green: 0.47, blue: 0.23)
private let good = Color(red: 0.29, green: 0.87, blue: 0.50)
private let bad = Color(red: 0.97, green: 0.44, blue: 0.44)
// --clay-300 (#e8a87c), the site's brand dot.
private let clayLight = Color(red: 0.91, green: 0.66, blue: 0.49)

// The bracket's position-badge palette, lifted from the app's BADGE tokens so
// a seed looks the same on the Lock Screen as it does inside the draw.
private let seedBg   = Color(red: 0.227, green: 0.184, blue: 0.063)  // #3a2f10
private let seedInk  = Color(red: 0.910, green: 0.780, blue: 0.400)  // #e8c766
private let seedLine = Color(red: 0.420, green: 0.333, blue: 0.094)  // #6b5518
private let rankBg   = Color(red: 0.169, green: 0.227, blue: 0.208)  // #2b3a35
private let rankInk  = Color(red: 0.722, green: 0.776, blue: 0.753)  // #b8c6c0
private let rankLine = Color(red: 0.624, green: 0.690, blue: 0.663)  // #9fb0a9

/// The serve indicator — the site's brand beacon, inner disc inside an outer
/// ring, doing an actual job rather than sitting in a corner as decoration.
///
/// IT DOES NOT PULSE, and that is not an oversight. Live Activity views are
/// rendered by WidgetKit as snapshots and redrawn only when the content state
/// changes; a `repeatForever` animation never runs there. Shipping one anyway
/// would leave dead code that reads like it should work and invites someone to
/// "fix" it later. The two rings still mark the server unmistakably, which is
/// the job. If serve ever needs to move, it has to move on a content update —
/// and updates are throttled to roughly one every 45s, which is not a pulse.
///
/// Renders its full footprint whether or not it is active, so the badges and
/// names below it stay on one vertical line.
private struct ServeBeacon: View {
    let active: Bool
    private let outer: CGFloat = 14
    private let inner: CGFloat = 6

    var body: some View {
        ZStack {
            if active {
                Circle().fill(clayLight.opacity(0.30)).frame(width: outer, height: outer)
                Circle().stroke(clayLight.opacity(0.55), lineWidth: 1).frame(width: outer, height: outer)
                Circle().fill(clayLight).frame(width: inner, height: inner)
            }
        }
        .frame(width: outer, height: outer)
        .accessibilityHidden(true)
    }
}

/// A real tournament seed, or the inferred one.
///
/// A GENUINE SEED IS A FACT ABOUT THE DRAW; an inferred seed is our own
/// arithmetic over the field. They are deliberately not the same colour — gold
/// carries the authority, grey stays quiet — and the box is a FIXED WIDTH so
/// every player's name starts at the same x whether their number is one digit
/// or three. That alignment is most of what makes two rows read as a match.
private struct SeedBadge: View {
    let seed: Int?
    let drawRank: Int?

    var body: some View {
        let isSeed = seed != nil
        let value = seed ?? drawRank
        return Group {
            if let value {
                Text("\(value)")
                    .font(.caption2).fontWeight(.bold)
                    .foregroundColor(isSeed ? seedInk : rankInk)
                    .monospacedDigit()
                    .lineLimit(1)
                    // fixedSize before the frame, for the same reason the score
                    // cells do it: overflow a tight box rather than wrap.
                    .fixedSize(horizontal: true, vertical: false)
                    .frame(width: 24, height: 16)
                    .background(RoundedRectangle(cornerRadius: 3).fill(isSeed ? seedBg : rankBg))
                    .overlay(RoundedRectangle(cornerRadius: 3).stroke(isSeed ? seedLine : rankLine, lineWidth: 0.5))
            } else {
                // No number at all still reserves the column, or the two names
                // would start at different x.
                Color.clear.frame(width: 24, height: 16)
            }
        }
    }
}

/// The round, top-right.
private struct RoundPill: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.caption2).fontWeight(.bold)
            .foregroundColor(ink.opacity(0.92))
            .lineLimit(1)
            .fixedSize(horizontal: true, vertical: false)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Capsule().fill(Color.white.opacity(0.14)))
            .overlay(Capsule().stroke(Color.white.opacity(0.20), lineWidth: 0.5))
    }
}

struct MatchLockScreenView: View {
    let context: ActivityViewContext<MatchActivityAttributes>

    private var state: MatchActivityAttributes.ContentState { context.state }
    private var attrs: MatchActivityAttributes { context.attributes }
    private var isOver: Bool { state.status == "final" || state.status == "ended_no_result" }

    /// Whether the per-player set columns have anything in them.
    private var hasSetColumns: Bool {
        guard let g = state.games, g.count == 2 else { return false }
        return g.contains { row in row.contains { !$0.isEmpty } }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(attrs.event_label.uppercased())
                    .font(.caption2).fontWeight(.bold)
                    .foregroundColor(muted)
                    .lineLimit(1)
                // Status sits with the event name because the round pill owns
                // the right corner. What is left here is short by design —
                // SUSPENDED or TIEBREAK, and nothing at all once a match is
                // over — so it shares the line without crowding either side.
                statusBadge
                Spacer(minLength: 6)
                if !attrs.round_name.isEmpty {
                    RoundPill(text: attrs.round_name)
                }
            }

            playerRow(side: 1, name: attrs.p1_name, seed: attrs.p1_seed, drawRank: attrs.p1_draw_rank)
            playerRow(side: 2, name: attrs.p2_name, seed: attrs.p2_seed, drawRank: attrs.p2_draw_rank)

            // ONE SCORE, NOT TWO. On the end push the card had both the
            // per-player set columns (3 3 5 / 6 6 7) AND this summary line
            // ("3-6 3-6 5-7") — the same result, written twice, one above the
            // other. The columns win: they sit on the row of the player who
            // won each set, which the line cannot show. So this renders only
            // when there are no columns to render, which is the case the line
            // was really for — an end push that arrives with no games grid.
            if let line = state.final_line, isOver, !hasSetColumns {
                Text(line).font(.caption).foregroundColor(muted)
            }
        }
        .padding(14)
        .activityBackgroundTint(Color.black.opacity(0.55))
        .activitySystemActionForegroundColor(ink)
    }

    @ViewBuilder private var statusBadge: some View {
        if state.status == "suspended" {
            Text("SUSPENDED").font(.caption2).fontWeight(.bold).foregroundColor(bad)
        } else if isOver {
            // NOTHING. Not "YOU WERE RIGHT"/"YOU WERE WRONG" — the tick or
            // cross already sits beside the player you picked, in the row it
            // belongs to, and the words said it a second time while wrapping
            // onto two lines in a corner with one line to spare.
            //
            // And not "FINAL" either when there is no pick. A finished match
            // is legible without a label: the score is on both rows, the
            // winner's is bold, and the serve beacon and live point are gone.
            // A word in the corner adds nothing to that.
            EmptyView()
        } else if state.tiebreak || state.match_tiebreak {
            Text("TIEBREAK").font(.caption2).fontWeight(.bold).foregroundColor(accent)
        }
    }

    private func playerRow(side: Int, name: String, seed: Int?, drawRank: Int?) -> some View {
        let picked = state.pick.side == side
        let won = state.winner == side
        return HStack(spacing: 6) {
            ServeBeacon(active: state.serving == side && !isOver)
            SeedBadge(seed: seed, drawRank: drawRank)

            // BOTH NAMES WHITE. Colouring the pick clay made the card look
            // like it was rating the two players rather than reporting a
            // match, and the star already says which one is yours — twice was
            // once too many. Weight still moves, because bold is about who is
            // winning, not about whose side you took.
            Text(name)
                .font(.subheadline)
                .fontWeight(picked || won ? .bold : .regular)
                .foregroundColor(ink)
                .lineLimit(1)
                .minimumScaleFactor(0.7)

            if picked {
                // Slightly larger once the match is decided: this is the whole
                // verdict now that the words are gone, rather than a marker
                // sitting beside a running score.
                Image(systemName: pickSymbol)
                    .font(isOver ? .footnote : .caption2)
                    .foregroundColor(pickColor)
            }

            Spacer(minLength: 8)
            setScores(side: side)
        }
    }

    private var pickSymbol: String {
        guard let correct = state.pick.correct else { return "star.fill" }
        return correct ? "checkmark.circle.fill" : "xmark.circle.fill"
    }

    private var pickColor: Color {
        guard let correct = state.pick.correct else { return accent }
        return correct ? good : bad
    }

    @ViewBuilder private func setScores(side: Int) -> some View {
        let row = (state.games?.indices.contains(side - 1) ?? false)
            ? state.games![side - 1] : []
        // spacing 4, not 6: equal-width cells cost roughly 8pt per set over the
        // content-width ones they replace, and by the fifth set that came
        // straight out of the player's name.
        HStack(spacing: 4) {
            ForEach(Array(row.enumerated()), id: \.offset) { _, g in
                Text(g.isEmpty ? "–" : g)
                    .font(.system(.subheadline, design: .rounded))
                    .fontWeight(.semibold)
                    .foregroundColor(ink)
                    .monospacedDigit()
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
                    // EQUAL, CENTRED COLUMNS. The two players' scores are two
                    // independent HStacks, so nothing lines them up unless
                    // every cell is the SAME width — content-width cells only
                    // appeared to work because every game score is one digit.
                    // A match tiebreak ("10") is two, and that row alone would
                    // have shifted out of step with the one above it.
                    // The frame goes AFTER fixedSize deliberately: the text
                    // keeps its ideal width and overflows a narrow cell rather
                    // than wrapping, which is the failure this file already
                    // carries a paragraph about.
                    .frame(width: 18, alignment: .center)
            }
            // The current point sits apart from the set scores, and only while
            // the feed actually has one — ESPN-sourced matches never do.
            //
            // fixedSize IS THE FIX, not the width. By the fifth set the row is
            // a name plus five set scores plus this, and SwiftUI resolves the
            // squeeze by WRAPPING rather than truncating — so "15" came out as
            // a 1 above a 5, which reads as two separate numbers. lineLimit
            // alone would not have helped; the text has to refuse to be
            // compressed at all, and let the name (which has
            // minimumScaleFactor) give up the space instead.
            if let point = state.point, point.indices.contains(side - 1), !isOver {
                Text(point[side - 1])
                    .font(.system(.subheadline, design: .rounded))
                    .fontWeight(.bold)
                    .foregroundColor(accent)
                    .monospacedDigit()
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
                    // Centred, not trailing. Right-aligned, "0" and "40" shared
                    // a right edge and nothing else, so the single digit sat
                    // out on its own away from the column above it.
                    .frame(width: 26, alignment: .center)
            }
        }
    }
}

struct UpsetAlertActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: MatchActivityAttributes.self) { context in
            MatchLockScreenView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Text(context.attributes.p1_name)
                        .font(.caption).fontWeight(.semibold)
                        .foregroundColor(context.state.pick.side == 1 ? accent : ink)
                        .lineLimit(1)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(context.attributes.p2_name)
                        .font(.caption).fontWeight(.semibold)
                        .foregroundColor(context.state.pick.side == 2 ? accent : ink)
                        .lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    Text(compactScore(context.state))
                        .font(.system(.body, design: .rounded))
                        .fontWeight(.bold)
                        .foregroundColor(ink)
                        .monospacedDigit()
                }
            } compactLeading: {
                // WHOSE match, not which side won a set. The old pair of set
                // counts read "2" and "2" — true, and useless: it named neither
                // player nor who was ahead. Three letters of the surname you
                // picked answers the first question in the space available.
                Text(pickTag(context.attributes, context.state))
                    .font(.caption2).fontWeight(.bold)
                    .foregroundColor(accent)
            } compactTrailing: {
                // Sets, YOUR pick's first, coloured by whether it is going your
                // way. Two glyphs and a colour is the whole story from a glance
                // at the top of the screen.
                Text(setsLine(context.state))
                    .font(.caption2).fontWeight(.bold).monospacedDigit()
                    .foregroundColor(leadColor(context.state))
            } minimal: {
                // Minimal is one glyph beside another app's activity: the only
                // thing worth saying is whether to look.
                Image(systemName: "circle.fill")
                    .font(.system(size: 9))
                    .foregroundColor(leadColor(context.state))
            }
        }
    }
}

/// Three letters of the surname this viewer picked — "COM" for Comesaña.
/// Falls back to the leader when there is no pick, so the island still names
/// the match rather than going blank.
private func pickTag(_ a: MatchActivityAttributes, _ s: MatchActivityAttributes.ContentState) -> String {
    let side = s.pick.side ?? (s.sets_won.count == 2 && s.sets_won[1] > s.sets_won[0] ? 2 : 1)
    let full = side == 2 ? a.p2_name : a.p1_name
    // Surname is the last whitespace-separated component; "Francisco Comesaña"
    // -> "COM". Doubles ("A / B") keeps the first pair's surname, which is the
    // best three letters available.
    let surname = full.split(separator: "/").first?
        .split(separator: " ").last.map(String.init) ?? full
    return String(surname.prefix(3)).uppercased()
}

/// "2–1" with the viewer's pick FIRST, so the left number is always theirs.
private func setsLine(_ s: MatchActivityAttributes.ContentState) -> String {
    guard s.sets_won.count == 2 else { return "0–0" }
    let side = s.pick.side ?? 1
    let mine = side == 2 ? s.sets_won[1] : s.sets_won[0]
    let theirs = side == 2 ? s.sets_won[0] : s.sets_won[1]
    return "\(mine)–\(theirs)"
}

/// Green ahead, red behind, clay level — against the PICK, not side one.
private func leadColor(_ s: MatchActivityAttributes.ContentState) -> Color {
    if let correct = s.pick.correct { return correct ? good : bad }
    guard s.sets_won.count == 2, s.pick.side != nil else { return accent }
    let side = s.pick.side ?? 1
    let mine = side == 2 ? s.sets_won[1] : s.sets_won[0]
    let theirs = side == 2 ? s.sets_won[0] : s.sets_won[1]
    if mine > theirs { return good }
    if theirs > mine { return bad }
    return accent
}

/// "6-4 3-6 2-1" from the games grid — the Dynamic Island has no room for rows.
private func compactScore(_ s: MatchActivityAttributes.ContentState) -> String {
    guard let games = s.games, games.count == 2 else { return "" }
    let a = games[0], b = games[1]
    var parts: [String] = []
    for i in 0..<min(a.count, b.count) where !(a[i].isEmpty && b[i].isEmpty) {
        parts.append("\(a[i].isEmpty ? "0" : a[i])-\(b[i].isEmpty ? "0" : b[i])")
    }
    return parts.joined(separator: "  ")
}

@main
struct UpsetAlertActivityBundle: WidgetBundle {
    var body: some Widget {
        UpsetAlertActivityWidget()
    }
}
