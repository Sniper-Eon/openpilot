import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
  ) -> Bool { true }

  func application(
    _ application: UIApplication,
    configurationForConnecting connectingSceneSession: UISceneSession,
    options: UIScene.ConnectionOptions
  ) -> UISceneConfiguration {
    let configuration = UISceneConfiguration(name: "Default Configuration", sessionRole: connectingSceneSession.role)
    configuration.delegateClass = SceneDelegate.self
    return configuration
  }
}

enum AppBootstrap {
  static let privacyKey = "tesnav.amap.privacy-consent.v1"
  private static var configuredKey: String?

  static func configureAMap() {
    guard let key = AMapKeySettings.current else { return }
    if let previous = configuredKey, previous != key { AMapNaviDriveManager.destroyInstance() }
    AMapSearchAPI.updatePrivacyShow(.didShow, privacyInfo: .didContain)
    AMapSearchAPI.updatePrivacyAgree(.didAgree)
    AMapNaviManagerConfig.shared().updatePrivacyShow(.didShow, privacyInfo: .didContain)
    AMapNaviManagerConfig.shared().updatePrivacyAgree(.didAgree)
    MAMapView.updatePrivacyShow(.didShow, privacyInfo: .didContain)
    MAMapView.updatePrivacyAgree(.didAgree)
    AMapServices.shared().enableHTTPS = true
    AMapServices.shared().apiKey = key
    configuredKey = key
    NavAssistClient.shared.start()
  }

  static func mainController() -> UIViewController {
    guard AMapKeySettings.current != nil else {
      return UINavigationController(rootViewController: AMapKeyViewController())
    }
    return UINavigationController(rootViewController: SearchViewController())
  }
}
