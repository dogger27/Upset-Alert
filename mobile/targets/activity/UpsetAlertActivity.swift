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

struct MatchLockScreenView: View {
    let context: ActivityViewContext<MatchActivityAttributes>

    private var state: MatchActivityAttributes.ContentState { context.state }
    private var attrs: MatchActivityAttributes { context.attributes }
    private var isOver: Bool { state.status == "final" || state.status == "ended_no_result" }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
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
        HStack(spacing: 6) {
            ForEach(Array(row.enumerated()), id: \.offset) { _, g in
                Text(g.isEmpty ? "–" : g)
                    .font(.system(.subheadline, design: .rounded))
                    .fontWeight(.semibold)
                    .foregroundColor(ink)
                    .monospacedDigit()
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
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
                    .frame(minWidth: 26, alignment: .trailing)
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
                Text("\(context.state.sets_won.first ?? 0)")
                    .fontWeight(.bold).monospacedDigit()
            } compactTrailing: {
                Text("\(context.state.sets_won.count > 1 ? context.state.sets_won[1] : 0)")
                    .fontWeight(.bold).monospacedDigit()
            } minimal: {
                Image(systemName: "tennisball.fill").foregroundColor(accent)
            }
        }
    }
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
