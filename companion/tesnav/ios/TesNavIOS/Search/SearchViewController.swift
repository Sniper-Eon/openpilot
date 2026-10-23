import CoreLocation
import UIKit

final class SearchViewController: UIViewController {
  private let searchAPI = AMapSearchAPI()!
  private let locationManager = CLLocationManager()
  private let searchBar = UISearchBar()
  private let currentAddressLabel = UILabel()
  private let connectionView = ConnectionStatusView()
  private let emptyStateLabel = UILabel()
  private let tableView = UITableView(frame: .zero, style: .insetGrouped)
  private var debounceWork: DispatchWorkItem?
  private var candidates: [Destination] = []
  private var latestLocation: CLLocation?
  private var lastReverseGeocodeLocation: CLLocation?
  private var lastResolvedAddress: String?
  private let history = SearchHistoryStore()
  private var historyRows: [SearchHistoryEntry] = []
  private var activeKeyword = ""
  private var showingHistory: Bool { activeKeyword.isEmpty }

  override func viewDidLoad() {
    super.viewDidLoad()
    title = "TesNav"
    view.backgroundColor = .systemGroupedBackground
    navigationController?.navigationBar.tintColor = .systemBlue
    searchAPI.delegate = self
    locationManager.delegate = self
    locationManager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
    locationManager.distanceFilter = 10
    configureUI()
    navigationItem.rightBarButtonItem = UIBarButtonItem(
      title: "设置",
      style: .plain,
      target: self,
      action: #selector(showSettings)
    )
    requestLocation()
    showHistory()
  }

  override func viewWillAppear(_ animated: Bool) {
    super.viewWillAppear(animated)
    if showingHistory { showHistory() }
  }

  deinit {
    debounceWork?.cancel()
    searchAPI.cancelAllRequests()
  }

  private func configureUI() {
    let heading = UILabel()
    heading.text = "想去哪里？"
    heading.font = UIFontMetrics(forTextStyle: .largeTitle).scaledFont(for: .systemFont(ofSize: 30, weight: .bold))
    heading.adjustsFontForContentSizeCategory = true
    heading.textColor = .label
    heading.numberOfLines = 2

    searchBar.translatesAutoresizingMaskIntoConstraints = false
    searchBar.delegate = self
    searchBar.placeholder = "搜索地点、道路或附近地标"
    searchBar.searchBarStyle = .minimal
    searchBar.searchTextField.font = .preferredFont(forTextStyle: .body)
    searchBar.searchTextField.adjustsFontForContentSizeCategory = true
    searchBar.searchTextField.backgroundColor = .secondarySystemGroupedBackground
    searchBar.searchTextField.textColor = .label
    searchBar.accessibilityIdentifier = "destinationSearch"
    searchBar.autocapitalizationType = .none
    searchBar.autocorrectionType = .no

    currentAddressLabel.translatesAutoresizingMaskIntoConstraints = false
    currentAddressLabel.font = .preferredFont(forTextStyle: .subheadline)
    currentAddressLabel.adjustsFontForContentSizeCategory = true
    currentAddressLabel.textColor = .label
    currentAddressLabel.numberOfLines = 3
    currentAddressLabel.text = "正在获取当前位置…"

    let locationIcon = UIImageView(image: UIImage(systemName: "location.fill"))
    locationIcon.tintColor = .systemBlue
    locationIcon.contentMode = .scaleAspectFit
    locationIcon.translatesAutoresizingMaskIntoConstraints = false
    let locationRow = UIStackView(arrangedSubviews: [locationIcon, currentAddressLabel])
    locationRow.axis = .horizontal
    locationRow.alignment = .center
    locationRow.spacing = 10
    locationRow.isLayoutMarginsRelativeArrangement = true
    locationRow.layoutMargins = UIEdgeInsets(top: 2, left: 4, bottom: 2, right: 4)
    locationIcon.widthAnchor.constraint(equalToConstant: 20).isActive = true
    locationIcon.heightAnchor.constraint(equalToConstant: 20).isActive = true

    tableView.translatesAutoresizingMaskIntoConstraints = false
    tableView.dataSource = self
    tableView.delegate = self
    tableView.keyboardDismissMode = .onDrag
    tableView.backgroundColor = .clear
    tableView.rowHeight = UITableView.automaticDimension
    tableView.estimatedRowHeight = 88
    tableView.sectionHeaderTopPadding = 8
    tableView.register(UITableViewCell.self, forCellReuseIdentifier: "candidate")

    let header = UIStackView(arrangedSubviews: [heading, searchBar, locationRow, connectionView])
    header.translatesAutoresizingMaskIntoConstraints = false
    header.axis = .vertical
    header.spacing = 14
    header.isLayoutMarginsRelativeArrangement = true
    header.layoutMargins = UIEdgeInsets(top: 12, left: 20, bottom: 8, right: 20)

    view.addSubview(header)
    view.addSubview(tableView)
    NSLayoutConstraint.activate([
      header.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
      header.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      header.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      tableView.topAnchor.constraint(equalTo: header.bottomAnchor),
      tableView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      tableView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      tableView.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),
    ])
    emptyStateLabel.font = .preferredFont(forTextStyle: .body)
    emptyStateLabel.adjustsFontForContentSizeCategory = true
    emptyStateLabel.textColor = .secondaryLabel
    emptyStateLabel.textAlignment = .center
    emptyStateLabel.numberOfLines = 0
    emptyStateLabel.text = "搜索你要去的地方\n选择地址后，即可查看多条路线"
    tableView.backgroundView = emptyStateLabel
  }

  private func requestLocation() {
    switch locationManager.authorizationStatus {
    case .notDetermined:
      locationManager.requestAlwaysAuthorization()
    case .authorizedAlways, .authorizedWhenInUse:
      locationManager.startUpdatingLocation()
    case .denied, .restricted:
      currentAddressLabel.text = "定位权限未开启，请到系统设置允许 TesNav 使用定位"
    @unknown default:
      currentAddressLabel.text = "无法读取定位权限状态"
    }
  }

  private func searchTips(keyword: String) {
    guard !keyword.isEmpty else {
      showHistory()
      return
    }
    let request = AMapInputTipsSearchRequest()
    request.keywords = keyword
    request.cityLimit = false
    if let location = latestLocation {
      let coordinate = amapCoordinate(location)
      request.location = String(format: "%.6f,%.6f", coordinate.longitude, coordinate.latitude)
    }
    searchAPI.aMapInputTipsSearch(request)
  }

  private func resolvePOI(keyword: String) {
    guard !keyword.isEmpty else { return }
    activeKeyword = keyword
    candidates = []
    emptyStateLabel.text = "正在查找匹配地点…"
    tableView.reloadData()
    let request = AMapPOIKeywordsSearchRequest()
    request.keywords = keyword
    request.cityLimit = false
    request.offset = 8
    request.page = 1
    request.sortrule = latestLocation == nil ? 1 : 0
    if let location = latestLocation {
      let coordinate = amapCoordinate(location)
      request.location = AMapGeoPoint.location(withLatitude: coordinate.latitude, longitude: coordinate.longitude)
    }
    searchAPI.aMapPOIKeywordsSearch(request)
  }

  private func reverseGeocode(_ location: CLLocation) {
    if let previous = lastReverseGeocodeLocation, location.distance(from: previous) < 30 { return }
    lastReverseGeocodeLocation = location
    let request = AMapReGeocodeSearchRequest()
    let coordinate = amapCoordinate(location)
    request.location = AMapGeoPoint.location(withLatitude: coordinate.latitude, longitude: coordinate.longitude)
    request.requireExtension = true
    searchAPI.aMapReGoecodeSearch(request)
  }

  private func destination(from tip: AMapTip) -> Destination? {
    guard let point = tip.location else { return nil }
    return Destination(
      name: tip.name.nonEmpty ?? "未命名地点",
      address: [tip.district.nonEmpty, tip.address.nonEmpty].compactMap { $0 }.joined(separator: " "),
      poiID: tip.uid.nonEmpty,
      latitude: Double(point.latitude),
      longitude: Double(point.longitude)
    )
  }

  private func destination(from poi: AMapPOI) -> Destination? {
    let point = poi.enterLocation ?? poi.location
    guard let point else { return nil }
    return Destination(
      name: poi.name.nonEmpty ?? "未命名地点",
      address: [poi.district.nonEmpty, poi.address.nonEmpty].compactMap { $0 }.joined(separator: " "),
      poiID: poi.uid.nonEmpty,
      latitude: Double(point.latitude),
      longitude: Double(point.longitude)
    )
  }

  private func amapCoordinate(_ location: CLLocation) -> CLLocationCoordinate2D {
    AMapCoordinateConvert(location.coordinate, .GPS)
  }

  @objc private func showSettings() {
    let status = NavAssistClient.shared.status()
    let message = "设备\(status.connection == .online ? "已连接" : "暂未连接")\n当前地址：\(status.deviceID ?? "等待发现")"
    let sheet = UIAlertController(title: "TesNav 设置", message: message, preferredStyle: .actionSheet)
    sheet.addAction(UIAlertAction(title: "语音播报频次", style: .default) { [weak self] _ in
      self?.navigationController?.pushViewController(NavigationSpeechViewController(), animated: true)
    })
    sheet.addAction(UIAlertAction(title: "高德 Key 与配置指南", style: .default) { [weak self] _ in
      self?.navigationController?.pushViewController(AMapKeyViewController(), animated: true)
    })
    sheet.addAction(UIAlertAction(title: "清空搜索历史", style: .destructive) { [weak self] _ in self?.confirmClearHistory() })
    sheet.addAction(UIAlertAction(title: "重新连接 C3XL", style: .default) { _ in
      NavAssistClient.shared.requestRediscovery()
    })
    sheet.addAction(UIAlertAction(title: "定位与本地网络权限", style: .default) { _ in
      guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
      UIApplication.shared.open(url)
    })
    sheet.addAction(UIAlertAction(title: "重新获取当前位置", style: .default) { [weak self] _ in
      self?.lastReverseGeocodeLocation = nil
      self?.currentAddressLabel.text = "正在更新当前位置…"
      self?.requestLocation()
    })
    sheet.addAction(UIAlertAction(title: "完成", style: .cancel))
    sheet.popoverPresentationController?.barButtonItem = navigationItem.rightBarButtonItem
    present(sheet, animated: true)
  }

  private func showHistory() {
    candidates = []
    historyRows = history.entries()
    emptyStateLabel.text = "搜索你要去的地方\n最近搜索会保留在本机"
    tableView.reloadData()
  }

  @objc private func confirmClearHistory() {
    let alert = UIAlertController(title: "清空搜索历史？", message: "仅删除本机的搜索记录。", preferredStyle: .alert)
    alert.addAction(UIAlertAction(title: "取消", style: .cancel))
    alert.addAction(UIAlertAction(title: "清空", style: .destructive) { [weak self] _ in
      self?.history.clear()
      if self?.showingHistory == true { self?.showHistory() }
    })
    present(alert, animated: true)
  }
}

extension SearchViewController: UISearchBarDelegate {
  func searchBar(_ searchBar: UISearchBar, textDidChange searchText: String) {
    debounceWork?.cancel()
    let keyword = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
    activeKeyword = keyword
    candidates = []
    tableView.reloadData()
    if keyword.isEmpty { showHistory(); return }
    let work = DispatchWorkItem { [weak self] in self?.searchTips(keyword: keyword) }
    debounceWork = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: work)
  }

  func searchBarSearchButtonClicked(_ searchBar: UISearchBar) {
    debounceWork?.cancel()
    searchBar.resignFirstResponder()
    let keyword = searchBar.text?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    history.record(query: keyword)
    resolvePOI(keyword: keyword)
  }
}

extension SearchViewController: UITableViewDataSource, UITableViewDelegate {
  func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
    let count = showingHistory ? historyRows.count : candidates.count
    emptyStateLabel.isHidden = count > 0
    return count
  }

  func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
    if showingHistory { return historyRows.isEmpty ? nil : "最近搜索 · 左滑可删除" }
    return candidates.isEmpty ? nil : "选择目的地 · \(candidates.count) 个地点"
  }

  func tableView(_ tableView: UITableView, viewForFooterInSection section: Int) -> UIView? {
    guard showingHistory, !historyRows.isEmpty else { return nil }
    let clear = UIButton(type: .system)
    clear.setTitle("清空搜索历史", for: .normal)
    clear.tintColor = .systemRed
    clear.addTarget(self, action: #selector(confirmClearHistory), for: .touchUpInside)
    return clear
  }

  func tableView(_ tableView: UITableView, heightForFooterInSection section: Int) -> CGFloat {
    showingHistory && !historyRows.isEmpty ? 48 : 0
  }

  func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
    let cell = tableView.dequeueReusableCell(withIdentifier: "candidate", for: indexPath)
    let entry = showingHistory ? historyRows[indexPath.row] : nil
    let destination = entry?.destination ?? (showingHistory ? nil : candidates[indexPath.row])
    var configuration = cell.defaultContentConfiguration()
    configuration.text = destination?.name ?? entry?.query
    configuration.secondaryText = destination?.address ?? "再次搜索"
    configuration.textProperties.font = .preferredFont(forTextStyle: .headline)
    configuration.textProperties.color = .label
    configuration.secondaryTextProperties.font = .preferredFont(forTextStyle: .subheadline)
    configuration.secondaryTextProperties.color = .secondaryLabel
    configuration.secondaryTextProperties.numberOfLines = 2
    configuration.image = UIImage(systemName: showingHistory ? "clock.arrow.circlepath" : "mappin.circle.fill")
    configuration.imageProperties.tintColor = .systemBlue
    configuration.imageProperties.maximumSize = CGSize(width: 30, height: 30)
    configuration.directionalLayoutMargins.top = 16
    configuration.directionalLayoutMargins.bottom = 16
    cell.contentConfiguration = configuration
    cell.accessoryType = .disclosureIndicator
    return cell
  }

  func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
    tableView.deselectRow(at: indexPath, animated: true)
    if showingHistory, historyRows[indexPath.row].destination == nil {
      let query = historyRows[indexPath.row].query
      searchBar.text = query
      history.record(query: query)
      resolvePOI(keyword: query)
      tableView.reloadData()
      return
    }
    let destination = showingHistory ? historyRows[indexPath.row].destination! : candidates[indexPath.row]
    history.record(destination: destination)
    navigationController?.pushViewController(RoutePlanningViewController(destination: destination), animated: true)
  }

  func tableView(_ tableView: UITableView, canEditRowAt indexPath: IndexPath) -> Bool { showingHistory }

  func tableView(_ tableView: UITableView, commit editingStyle: UITableViewCell.EditingStyle, forRowAt indexPath: IndexPath) {
    guard showingHistory, editingStyle == .delete else { return }
    history.remove(historyRows[indexPath.row])
    showHistory()
  }
}

extension SearchViewController: CLLocationManagerDelegate {
  func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) { requestLocation() }

  func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
    guard let location = locations.last, location.horizontalAccuracy >= 0 else { return }
    latestLocation = location
    currentAddressLabel.text = lastResolvedAddress.map { "当前位置：\($0)" } ?? "已获取当前位置，正在解析地址…"
    reverseGeocode(location)
  }

  func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
    currentAddressLabel.text = "定位失败：\(error.localizedDescription)"
  }
}

extension SearchViewController: AMapSearchDelegate {
  func onInputTipsSearchDone(_ request: AMapInputTipsSearchRequest!, response: AMapInputTipsSearchResponse!) {
    guard !activeKeyword.isEmpty, request?.keywords == activeKeyword else { return }
    let tips = response?.tips ?? []
    candidates = tips.compactMap(destination(from:))
    emptyStateLabel.text = "正在查找附近的匹配地点…"
    if candidates.isEmpty, let keyword = request?.keywords.nonEmpty { resolvePOI(keyword: keyword) }
    tableView.reloadData()
  }

  func onPOISearchDone(_ request: AMapPOISearchBaseRequest!, response: AMapPOISearchResponse!) {
    guard !activeKeyword.isEmpty, let keywordRequest = request as? AMapPOIKeywordsSearchRequest,
          keywordRequest.keywords == activeKeyword else { return }
    candidates = (response?.pois ?? []).prefix(8).compactMap(destination(from:))
    emptyStateLabel.text = "没有找到匹配地点\n试试更完整的地名或附近地标"
    tableView.reloadData()
  }

  func onReGeocodeSearchDone(_ request: AMapReGeocodeSearchRequest!, response: AMapReGeocodeSearchResponse!) {
    if let address = response?.regeocode.formattedAddress.nonEmpty {
      lastResolvedAddress = address
      currentAddressLabel.text = "当前位置：\(address)"
    }
  }

  func aMapSearchRequest(_ request: Any!, didFailWithError error: Error!) {
    let details = error as NSError
    if request is AMapReGeocodeSearchRequest {
      currentAddressLabel.text = AMapSearchFailureMessage.currentAddress(details)
    } else {
      if showingHistory { return }
      if let tips = request as? AMapInputTipsSearchRequest, tips.keywords != activeKeyword { return }
      if let poi = request as? AMapPOIKeywordsSearchRequest, poi.keywords != activeKeyword { return }
      candidates = []
      emptyStateLabel.text = "搜索暂时不可用\n请检查网络后重试"
      currentAddressLabel.text = AMapSearchFailureMessage.search(details)
      tableView.reloadData()
    }
  }
}

enum AMapSearchFailureMessage {
  static func currentAddress(_ error: NSError) -> String {
    "当前位置已获取，\(reason(error))"
  }

  static func search(_ error: NSError) -> String {
    "目的地搜索失败：\(reason(error))"
  }

  private static func reason(_ error: NSError) -> String {
    switch error.code {
    case 1002:
      "高德 Key 非法或已过期（1002）"
    case 1003:
      "高德 Key 没有开通搜索服务（1003）"
    case 1004:
      "高德 Key 今日调用量已用完（1004）"
    case 1005:
      "高德请求过于频繁，请稍后重试（1005）"
    case 1008:
      "高德 iOS Key 与 Bundle ID com.garan.tesnav.ios 不匹配（1008）"
    case 1009:
      "高德 Key 绑定的平台不是 iOS（1009）"
    case 1102, 1103, 1802:
      "连接高德服务超时（\(error.code)）"
    case 1804, 1805, 1806:
      "无法连接高德服务，请检查手机网络（\(error.code)）"
    default:
      "高德服务错误 \(error.domain)/\(error.code)：\(error.localizedDescription)"
    }
  }
}

private extension String {
  var nonEmpty: String? { isEmpty ? nil : self }
}
