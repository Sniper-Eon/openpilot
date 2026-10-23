import XCTest
@testable import TesNavIOS

final class SpeechSettingsTests: XCTestCase {
  func testDefaultsPersistenceAndMuteRestore() {
    let suite = "tesnav-speech-test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let settings = NavigationSpeechSettings(defaults: defaults)
    XCTAssertEqual(settings.mode, .concise)
    settings.save(.detailed)
    XCTAssertEqual(NavigationSpeechSettings(defaults: defaults).mode, .detailed)
    settings.save(.muted)
    XCTAssertEqual(NavigationSpeechSettings(defaults: defaults).mode, .muted)
    XCTAssertEqual(settings.resumedMode, .detailed)
    settings.save(.concise)
    settings.save(.muted)
    XCTAssertEqual(settings.resumedMode, .concise)
    defaults.set(999, forKey: "navigationSpeechMode")
    XCTAssertEqual(settings.mode, .concise)
  }
}
