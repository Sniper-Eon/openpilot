import UIKit

final class AMapKeyViewController: UIViewController {
  private let keyField = UITextField()
  private let messageLabel = UILabel()

  override func viewDidLoad() {
    super.viewDidLoad()
    title = "高德 Key 配置"
    view.backgroundColor = .systemGroupedBackground
    let scroll = UIScrollView()
    scroll.translatesAutoresizingMaskIntoConstraints = false
    scroll.keyboardDismissMode = .interactive
    let stack = UIStackView()
    stack.translatesAutoresizingMaskIntoConstraints = false
    stack.axis = .vertical
    stack.spacing = 18
    scroll.addSubview(stack)
    view.addSubview(scroll)
    NSLayoutConstraint.activate([
      scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
      scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      scroll.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor),
      stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 24),
      stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -24),
      stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 24),
      stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -28),
      stack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -48),
    ])
    stack.addArrangedSubview(label("连接高德导航", style: .largeTitle))
    stack.addArrangedSubview(label(AMapKeySettings.current == nil
      ? "首次使用，请先填写高德 iOS Key。配置保存在本机，之后无需重复填写。"
      : "高德 Key 已配置。你可以在这里查看申请说明或更换 Key。"))
    keyField.placeholder = "粘贴 32 位高德 iOS Key"
    keyField.text = AMapKeySettings.current
    keyField.font = .preferredFont(forTextStyle: .body)
    keyField.adjustsFontForContentSizeCategory = true
    keyField.borderStyle = .roundedRect
    keyField.isSecureTextEntry = true
    keyField.autocapitalizationType = .none
    keyField.autocorrectionType = .no
    keyField.accessibilityIdentifier = "amapKeyInput"
    keyField.heightAnchor.constraint(greaterThanOrEqualToConstant: 52).isActive = true
    stack.addArrangedSubview(keyField)
    stack.addArrangedSubview(button("显示 / 隐藏 Key") { [weak self] in self?.keyField.isSecureTextEntry.toggle() })
    messageLabel.font = .preferredFont(forTextStyle: .subheadline)
    messageLabel.numberOfLines = 0
    messageLabel.textColor = .systemRed
    stack.addArrangedSubview(messageLabel)
    stack.addArrangedSubview(button("保存并进入", filled: true) { [weak self] in self?.save() })
    stack.addArrangedSubview(label("如何申请 Key", style: .title2))
    stack.addArrangedSubview(label("1. 打开高德开放平台控制台，注册 / 登录并按提示完成账号认证。\n\n2. 进入「应用管理 → 我的应用」，创建应用并添加 Key，服务平台选择「iOS 平台 SDK」。\n\n3. 将下方 Bundle ID 填入对应安全码 / 应用标识字段。\n\n4. 复制生成的 Key，返回本页粘贴并保存。地图、搜索、定位和导航将使用此 Key。"))
    let bundleID = Bundle.main.bundleIdentifier ?? "com.garan.tesnav.ios"
    stack.addArrangedSubview(label("应用 Bundle ID\n\(bundleID)", style: .callout))
    stack.addArrangedSubview(button("复制 Bundle ID") { [weak self] in
      UIPasteboard.general.string = bundleID
      self?.messageLabel.textColor = .systemGreen
      self?.messageLabel.text = "Bundle ID 已复制"
    })
    stack.addArrangedSubview(label("iOS 与 Android 的 Key 不能互用。若提示鉴权失败，请核对平台、Bundle ID 与高德账号服务权限。Key 保存成功不代表高德已通过鉴权。", style: .footnote))
    stack.addArrangedSubview(button("打开高德控制台") { [weak self] in self?.open("https://console.amap.com/") })
    stack.addArrangedSubview(button("查看官方 iOS 配置说明") { [weak self] in
      self?.open("https://lbs.amap.com/api/ios-navi-sdk/guide/create-project/get-key")
    })
  }

  private func label(_ text: String, style: UIFont.TextStyle = .body) -> UILabel {
    let label = UILabel()
    label.text = text
    label.font = .preferredFont(forTextStyle: style)
    label.adjustsFontForContentSizeCategory = true
    label.numberOfLines = 0
    label.textColor = .label
    return label
  }

  private func button(_ title: String, filled: Bool = false, action: @escaping () -> Void) -> UIButton {
    let button = UIButton(type: .system)
    var config = filled ? UIButton.Configuration.filled() : UIButton.Configuration.tinted()
    config.title = title
    config.cornerStyle = .large
    config.contentInsets = NSDirectionalEdgeInsets(top: 14, leading: 12, bottom: 14, trailing: 12)
    button.configuration = config
    button.addAction(UIAction { _ in action() }, for: .touchUpInside)
    return button
  }

  private func save() {
    do {
      try AMapKeySettings.save(keyField.text ?? "")
      guard let window = view.window else { return }
      AppBootstrap.configureAMap()
      window.rootViewController = AppBootstrap.mainController()
    } catch {
      messageLabel.textColor = .systemRed
      messageLabel.text = error.localizedDescription
    }
  }

  private func open(_ address: String) {
    guard let url = URL(string: address) else { return }
    UIApplication.shared.open(url)
  }
}
