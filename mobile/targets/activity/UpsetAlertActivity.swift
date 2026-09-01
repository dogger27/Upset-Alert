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
// --clay-300 (#e8a87c), the site's brand dot. Lighter than `accent`: the mark
// sits on a dark tint and the darker clay reads as mud at 7pt.
private let clayLight = Color(red: 0.91, green: 0.66, blue: 0.49)

/// The brand mark — the site's navbar dot, redrawn rather than shipped.
///
/// DRAWN, NOT AN ASSET, and deliberately: a widget extension cannot reach the
/// main app's bundle, so a bitmap here would need its own copy in the target's
/// asset catalogue at three scales, and it would still be a raster of two
/// circles. This is the same mark as `.navbar-brand-dot` — a clay disc inside a
/// soft ring at 28% — minus the pulse, which has no business animating on a
/// Lock Screen.
///
/// No wordmark: iOS already prints "Upset Alert" directly above the card, so a
/// second one would say the app's name twice in two centimetres.
private struct BrandDot: View {
    var size: CGFloat = 7

    var body: some View {
        Circle()
            .fill(clayLight)
            .frame(width: size, height: size)
            // The halo is a disc BEHIND the dot rather than a stroke on it: a
            // stroke straddles the edge and eats into the solid centre, which
            // at this size turns the mark into a smudge.
            .background(
                Circle()
                    .fill(clayLight.opacity(0.28))
                    .frame(width: size + 7, height: size + 7)
            )
            // Reserve what the halo actually occupies, or it clips against the
            // neighbouring text.
            .frame(width: size + 7, height: size + 7)
            .accessibilityHidden(true)
    }
}

struct MatchLockScreenView: View {
    let context: ActivityViewContext<MatchActivityAttributes>

    private var state: MatchActivityAttributes.ContentState { context.state }
    private var attrs: MatchActivityAttributes { context.attributes }
    private var isOver: Bool { state.status == "final" || state.status == "ended_no_result" }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                BrandDot()
                Text(attrs.event_label.uppercased())
                    .font(.caption2).fontWeight(.bold)
                    .foregroundColor(muted)
                if !attrs.round_name.isEmpty {
                    Text(attrs.round_name)
                        .font(.caption2)
                        .foregroundColor(muted)
                }
                Spacer()
                statusBadge
            }

            playerRow(side: 1, name: attrs.p1_name, seed: attrs.p1_seed)
            playerRow(side: 2, name: attrs.p2_name, seed: attrs.p2_seed)

            if let line = state.final_line, isOver {
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
            // The payoff: right or wrong, stated plainly, at the moment it is
            // finally knowable.
            if let correct = state.pick.correct {
                Text(correct ? "YOU WERE RIGHT" : "YOU WERE WRONG")
                    .font(.caption2).fontWeight(.bold)
                    .foregroundColor(correct ? good : bad)
            } else {
                Text("FINAL").font(.caption2).fontWeight(.bold).foregroundColor(muted)
            }
        } else if state.tiebreak || state.match_tiebreak {
            Text("TIEBREAK").font(.caption2).fontWeight(.bold).foregroundColor(accent)
        }
    }

    private func playerRow(side: Int, name: String, seed: Int?) -> some View {
        let picked = state.pick.side == side
        let won = state.winner == side
        return HStack(spacing: 6) {
            // Serving. A dot rather than a label: it changes every game and a
            // word would draw more attention than it deserves.
            Circle()
                .fill(state.serving == side && !isOver ? accent : Color.clear)
                .frame(width: 6, height: 6)

            if let seed = seed {
                Text("\(seed)").font(.caption2).foregroundColor(muted)
            }

            Text(name)
                .font(.subheadline)
                .fontWeight(picked || won ? .bold : .regular)
                .foregroundColor(picked ? accent : ink)
                .lineLimit(1)
                .minimumScaleFactor(0.7)

            if picked {
                Image(systemName: pickSymbol)
                    .font(.caption2)
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
