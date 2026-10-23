import Foundation

enum NavigationSpeechMode: Int, CaseIterable {
  case muted = 0, concise = 1, detailed = 2

  var title: String {
    switch self {
    case .muted: return "静音"
    case .concise: return "简洁播报（较少）"
    case .detailed: return "详细播报（较多）"
    }
  }
}

final class NavigationSpeechSettings {
  static let shared = NavigationSpeechSettings()
  private let defaults: UserDefaults
  init(defaults: UserDefaults = .standard) { self.defaults = defaults }

  var mode: NavigationSpeechMode {
    guard let value = defaults.object(forKey: "navigationSpeechMode") as? Int else { return .concise }
    return NavigationSpeechMode(rawValue: value) ?? .concise
  }

  var resumedMode: NavigationSpeechMode {
    let saved = NavigationSpeechMode(rawValue: defaults.integer(forKey: "navigationSpeechAudibleMode"))
    return saved == .detailed ? .detailed : .concise
  }

  func save(_ mode: NavigationSpeechMode) {
    defaults.set(mode.rawValue, forKey: "navigationSpeechMode")
    if mode != .muted { defaults.set(mode.rawValue, forKey: "navigationSpeechAudibleMode") }
  }
}
