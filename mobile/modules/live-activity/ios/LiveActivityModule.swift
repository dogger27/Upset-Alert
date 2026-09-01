import ActivityKit
import ExpoModulesCore

/*
 The app half of the Live Activity feature.

 It does NOT start activities. The SERVER does, using an iOS 17.2+
 push-to-start token — and that choice is what makes the feature work when it
 matters. A match that becomes worth watching at 2am is exactly the one the
 user is not holding their phone for; requiring the app to be open to start an
 activity would mean it only ever appears for people already watching, who
 need it least.

 So this module's whole job is to hand the server two kinds of token:

   pushToStartToken  once per install, lets the server BEGIN an activity
   activity token    per running activity, lets the server UPDATE that one

 Both are reissued by iOS without warning, so both are observed continuously
 rather than fetched once. The listeners are started from JS after sign-in,
 because the tokens are useless until there is a user to attach them to.
*/

// Must match targets/activity/MatchActivityAttributes.swift EXACTLY. Two
// copies is not ideal, but an app target and a widget extension are separate
// compilation units and Expo modules cannot see the extension's sources.
// The wire format is owned by live_activity_content.py; both copies mirror it.
//
// "EXACTLY" IS NOW CHECKED, because saying it here did not prevent it: seed
// badges shipped in a build that never drew one, since p1_draw_rank was added
// to the widget's copy and not to this one. THIS struct is what the app encodes
// with, so a field missing here is dropped before the widget can ever see it —
// and nothing errors. Run `node liveactivity.test.mjs`.
struct MatchActivityAttributes: ActivityAttributes {
  public struct ContentState: Codable, Hashable {
    var v: Int
    var games: [[String]]?
    var point: [String]?
    var tiebreak: Bool
    var match_tiebreak: Bool
    var serving: Int?
    var sets_won: [Int]
    var status: String
    var winner: Int?
    var final_line: String?
    var pick: Pick
    var at: String
    var stale_after: String

    public struct Pick: Codable, Hashable {
      var side: Int?
      var correct: Bool?
    }
  }

  var match_id: Int
  var p1_entry_id: Int?
  var p1_name: String
  var p2_name: String
  var p1_seed: Int?
  var p2_seed: Int?
  var p1_draw_rank: Int?
  var p2_draw_rank: Int?
  var round_name: String
  var event_label: String
}

public class LiveActivityModule: Module {
  private var pushToStartTask: Task<Void, Never>?
  private var activityTask: Task<Void, Never>?

  public func definition() -> ModuleDefinition {
    Name("LiveActivity")

    Events("onPushToStartToken", "onActivityToken", "onActivityEnded")

    // Whether this OS can do any of it. iOS 16.2 brought push updates;
    // push-to-start needs 17.2. Reported separately so JS can tell "no Live
    // Activities at all" from "the server cannot start one for you".
    Function("capabilities") { () -> [String: Any] in
      if #available(iOS 16.2, *) {
        let info = ActivityAuthorizationInfo()
        var out: [String: Any] = [
          "supported": true,
          "enabled": info.areActivitiesEnabled,
          "pushToStart": false,
        ]
        if #available(iOS 17.2, *) { out["pushToStart"] = true }
        return out
      }
      return ["supported": false, "enabled": false, "pushToStart": false]
    }

    Function("attributesType") { () -> String in
      // The server sends this back in the `attributes-type` field of a
      // push-to-start payload; ActivityKit matches it against the struct name.
      return String(describing: MatchActivityAttributes.self)
    }

    AsyncFunction("startListening") { () -> Void in
      self.beginObserving()
    }

    // What ActivityKit believes is running, for reconciliation at launch.
    // Neither side is reliable alone: the app is killed without telling the
    // server, and the server cannot see a user swiping an activity away — or,
    // as happened here, a new build replacing the one that owned it.
    Function("runningActivities") { () -> [[String: Any]] in
      guard #available(iOS 16.2, *) else { return [] }
      return Activity<MatchActivityAttributes>.activities.map {
        ["activityId": $0.id, "matchId": $0.attributes.match_id]
      }
    }

    // Start one, and hand back its id.
    //
    // JSON STRINGS RATHER THAN BRIDGED DICTIONARIES, deliberately. The server
    // builds both halves with live_activity_content.py, which owns the wire
    // format; passing them through as opaque JSON means the client cannot
    // quietly reshape a field on the way past, and the same JSONDecoder that
    // will handle every push handles the first one. A dictionary bridged
    // key-by-key would be a second, subtly different parser.
    AsyncFunction("startActivity") { (attributesJson: String, stateJson: String) -> String in
      guard #available(iOS 16.2, *) else {
        throw NSError(domain: "LiveActivity", code: 1, userInfo: [
          NSLocalizedDescriptionKey: "Live Activities need iOS 16.2",
        ])
      }
      guard ActivityAuthorizationInfo().areActivitiesEnabled else {
        throw NSError(domain: "LiveActivity", code: 2, userInfo: [
          NSLocalizedDescriptionKey: "Live Activities are turned off in Settings",
        ])
      }

      let decoder = JSONDecoder()
      let attributes = try decoder.decode(
        MatchActivityAttributes.self, from: Data(attributesJson.utf8))
      let state = try decoder.decode(
        MatchActivityAttributes.ContentState.self, from: Data(stateJson.utf8))

      // One per match. Starting a second for a match already on the Lock
      // Screen gives the user two of the same thing and the server two rows to
      // update, and only one of them can ever be dismissed by tapping.
      if let existing = Activity<MatchActivityAttributes>.activities.first(
        where: { $0.attributes.match_id == attributes.match_id }
      ) {
        return existing.id
      }

      // .token asks iOS for a push token so the server can update it. Without
      // it the activity is frozen at whatever it started with.
      let activity = try Activity.request(
        attributes: attributes,
        content: .init(state: state, staleDate: nil),
        pushType: .token
      )
      return activity.id
    }

    AsyncFunction("stopListening") { () -> Void in
      self.pushToStartTask?.cancel()
      self.activityTask?.cancel()
      self.pushToStartTask = nil
      self.activityTask = nil
    }

    // Ending everything is the sign-out path: a Lock Screen belonging to an
    // account that is no longer signed in has no business still updating.
    AsyncFunction("endAll") { () -> Void in
      if #available(iOS 16.2, *) {
        for activity in Activity<MatchActivityAttributes>.activities {
          await activity.end(nil, dismissalPolicy: .immediate)
        }
      }
    }

    OnDestroy {
      self.pushToStartTask?.cancel()
      self.activityTask?.cancel()
    }
  }

  private func beginObserving() {
    guard #available(iOS 17.2, *) else { return }

    pushToStartTask?.cancel()
    pushToStartTask = Task { [weak self] in
      // A for-await over an AsyncSequence that iOS keeps open. It yields again
      // whenever the token is reissued, which is why this is not a one-shot
      // read.
      for await data in Activity<MatchActivityAttributes>.pushToStartTokenUpdates {
        let token = data.map { String(format: "%02x", $0) }.joined()
        self?.sendEvent("onPushToStartToken", ["token": token])
      }
    }

    activityTask?.cancel()
    activityTask = Task { [weak self] in
      for await activity in Activity<MatchActivityAttributes>.activityUpdates {
        // Each activity has its OWN token for updates, separate from the
        // push-to-start one. Observed in a child task so one activity ending
        // does not stop us watching the others.
        Task {
          for await tokenData in activity.pushTokenUpdates {
            let token = tokenData.map { String(format: "%02x", $0) }.joined()
            self?.sendEvent("onActivityToken", [
              "activityId": activity.id,
              "matchId": activity.attributes.match_id,
              "token": token,
            ])
          }
        }
        Task {
          for await state in activity.activityStateUpdates where state == .dismissed || state == .ended {
            self?.sendEvent("onActivityEnded", [
              "activityId": activity.id,
              "matchId": activity.attributes.match_id,
            ])
          }
        }
      }
    }
  }
}
