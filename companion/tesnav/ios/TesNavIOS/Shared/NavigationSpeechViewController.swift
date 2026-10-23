import UIKit

enum NavigationSpeech {
  @discardableResult
  static func apply(_ mode: NavigationSpeechMode) -> Bool {
    let manager = AMapNaviDriveManager.sharedInstance()
    if mode == .muted {
      manager.pauseNaviSpeech()
    } else {
      guard manager.setBroadcastMode(mode == .concise ? .concise : .detailed) else { return false }
      manager.resumeNaviSpeech()
    }
    return true
  }
}

final class NavigationSpeechViewController: UITableViewController {
  private let choices: [NavigationSpeechMode] = [.concise, .detailed, .muted]

  init() { super.init(style: .insetGrouped) }
  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidLoad() {
    super.viewDidLoad()
    title = "语音播报频次"
    tableView.register(UITableViewCell.self, forCellReuseIdentifier: "mode")
  }

  override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int { choices.count }

  override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
    let cell = tableView.dequeueReusableCell(withIdentifier: "mode", for: indexPath)
    cell.textLabel?.text = choices[indexPath.row].title
    cell.accessoryType = choices[indexPath.row] == NavigationSpeechSettings.shared.mode ? .checkmark : .none
    return cell
  }

  override func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? {
    "设置自动保存。简洁／详细由高德安排播报，切换后在下次算路时生效；不会强制重算当前路线。静音立即停止全部语音提醒。此设置不影响发送给 C3XL 的导航信息频率。"
  }

  override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
    tableView.deselectRow(at: indexPath, animated: true)
    let mode = choices[indexPath.row]
    guard NavigationSpeech.apply(mode) else {
      let alert = UIAlertController(title: "设置未生效", message: "高德未接受播报模式，请稍后重试。", preferredStyle: .alert)
      alert.addAction(UIAlertAction(title: "确定", style: .default))
      present(alert, animated: true)
      return
    }
    NavigationSpeechSettings.shared.save(mode)
    tableView.reloadData()
  }
}
