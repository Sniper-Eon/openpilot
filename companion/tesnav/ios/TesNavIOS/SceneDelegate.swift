import UIKit

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
  var window: UIWindow?

  func scene(
    _ scene: UIScene,
    willConnectTo session: UISceneSession,
    options connectionOptions: UIScene.ConnectionOptions
  ) {
    guard let windowScene = scene as? UIWindowScene else { return }
    let window = UIWindow(windowScene: windowScene)
    if UserDefaults.standard.bool(forKey: AppBootstrap.privacyKey) {
      AppBootstrap.configureAMap()
      window.rootViewController = AppBootstrap.mainController()
    } else {
      let consent = PrivacyConsentViewController()
      consent.onAgree = { [weak window] in
        guard let window else { return }
        UserDefaults.standard.set(true, forKey: AppBootstrap.privacyKey)
        AppBootstrap.configureAMap()
        window.rootViewController = AppBootstrap.mainController()
        UIView.transition(with: window, duration: 0.25, options: .transitionCrossDissolve, animations: nil)
      }
      window.rootViewController = consent
    }
    window.makeKeyAndVisible()
    self.window = window
  }
}
