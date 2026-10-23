import UIKit

final class PrivacyConsentViewController: UIViewController {
  var onAgree: (() -> Void)?

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = .systemBackground

    let titleLabel = UILabel()
    titleLabel.font = .preferredFont(forTextStyle: .title1)
    titleLabel.text = "隐私与导航服务"

    let descriptionLabel = UILabel()
    descriptionLabel.font = .preferredFont(forTextStyle: .body)
    descriptionLabel.numberOfLines = 0
    descriptionLabel.text = "TesNav 使用高德地图、定位和导航 SDK 获取当前位置、搜索目的地、规划路线并进行语音导航；导航状态会发送到同一局域网内自动发现的 C3XL。应用不会要求或保存共享 Token。"

    let agreeButton = UIButton(type: .system)
    var configuration = UIButton.Configuration.filled()
    configuration.title = "同意并继续"
    configuration.cornerStyle = .large
    agreeButton.configuration = configuration
    agreeButton.addTarget(self, action: #selector(agree), for: .touchUpInside)

    let stack = UIStackView(arrangedSubviews: [titleLabel, descriptionLabel, agreeButton])
    stack.translatesAutoresizingMaskIntoConstraints = false
    stack.axis = .vertical
    stack.spacing = 24
    view.addSubview(stack)
    NSLayoutConstraint.activate([
      stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 28),
      stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -28),
      stack.centerYAnchor.constraint(equalTo: view.centerYAnchor),
      agreeButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 50),
    ])
  }

  @objc private func agree() { onAgree?() }
}
