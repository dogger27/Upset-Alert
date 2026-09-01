import ActivityKit
import Foundation

// THE WIRE FORMAT. Mirrors backend/app/services/live_activity_content.py,
// which owns CONTENT_VERSION and is the only thing allowed to build these.
//
// PROPERTY NAMES ARE THE JSON KEYS ON PURPOSE. Swift would prefer camelCase
// with a CodingKeys mapping, but every mapping is a place to get one key
// wrong — and getting one wrong here does not raise. APNs returns 200 for a
// payload the app cannot decode; the activity simply stops moving, showing a
// stale score with no error anywhere. Matching the keys exactly removes that
// entire class of failure at the cost of some Swift style.
//
// Anything OPTIONAL here is optional in the Python too. `games` is nil before
// a set exists, and `point` is nil whenever the source is ESPN, which
// publishes game counts and no current point at all — rendering "0-0" there
// would confidently show love-all through a whole game.

struct MatchActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        /// CONTENT_VERSION on the server. Present so a client that is behind
        /// can recognise a shape it does not fully understand instead of
        /// guessing.
        var v: Int

        /// [[p1 games per set], [p2 games per set]] — strings, because a set
        /// not yet reached is "" rather than 0.
        var games: [[String]]?
        /// ["40", "30"] — the current point, or nil when the feed has none.
        var point: [String]?
        var tiebreak: Bool
        var match_tiebreak: Bool
        /// 1 or 2 — which player is serving, or nil if unknown.
        var serving: Int?
        /// Completed sets won, [p1, p2].
        var sets_won: [Int]

        /// in_progress | suspended | final | ended_no_result
        var status: String
        /// 1 or 2 once decided.
        var winner: Int?
        /// "6-4 3-6 7-6" on the end push.
        var final_line: String?

        /// THIS viewer's pick. The reason a fantasy Lock Screen beats a scores
        /// app: the number that matters is not the score, it is whether the
        /// score is going your way.
        var pick: Pick

        var at: String
        var stale_after: String

        public struct Pick: Codable, Hashable {
            /// 1 or 2 — which side this user predicted, nil if they did not.
            var side: Int?
            /// nil while undecided, then true/false.
            var correct: Bool?
        }
    }

    // The immutable half, sent once when the activity starts.
    var match_id: Int
    /// Orientation is NOT obvious: the poller flips Sofascore's home/away into
    /// the match's own order. This travels so the widget never has to assume
    /// its own ordering matches the server's.
    var p1_entry_id: Int?
    var p1_name: String
    var p2_name: String
    var p1_seed: Int?
    var p2_seed: Int?
    /// The INFERRED seed — where the player sits once the whole field is
    /// ordered. Optional in both directions on purpose: a payload from a server
    /// that predates these decodes fine, and a server that sends them to an
    /// older build is simply ignored. Getting that wrong is not a crash, it is
    /// an activity that silently stops updating while APNs still returns 200.
    var p1_draw_rank: Int?
    var p2_draw_rank: Int?
    var round_name: String
    var event_label: String
}
