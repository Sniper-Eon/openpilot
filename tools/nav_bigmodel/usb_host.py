"""Mac USB host transport for the pinned Jetlink vendor interface.

Uses Jetlink's existing framing, bounds and burst-padding implementation.
No gadget configuration or device setting changes occur here.
"""
from jetlink import protocol as P
from jetlink.transport.base import StreamTransport, LinkError


class UsbHost(StreamTransport):
  packet_size = 1024
  read_slack = 16384
  rx_align = P.GADGET_TX_ALIGN

  def __init__(self):
    import usb.core
    import usb.util
    import usb.backend.libusb1
    import libusb_package
    super().__init__()
    self.usb = usb
    backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    self.device = usb.core.find(idVendor=P.USB_VID, idProduct=P.USB_PID, backend=backend)
    if self.device is None:
      raise LinkError('No Jetlink USB gadget connected')
    configuration = self.device.get_active_configuration()
    matches = [i for i in configuration if (i.bInterfaceClass, i.bInterfaceSubClass, i.bInterfaceProtocol) == P.USB_VENDOR_CLASS]
    if len(matches) != 1:
      raise LinkError('Expected one Jetlink vendor interface')
    interface = matches[0]
    self.interface = interface.bInterfaceNumber
    endpoints = [e for e in interface if usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK]
    self.incoming = next(e for e in endpoints if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
    self.outgoing = next(e for e in endpoints if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    usb.util.claim_interface(self.device, self.interface)

  def _write(self, bufs):
    data = b''.join(bufs)
    timeout = self._write_timeout(5)
    try:
      return self.outgoing.write(data, timeout=max(1, int(timeout * 1000)))
    except self.usb.core.USBError as error:
      raise LinkError(str(error)) from error

  def _read_into(self, dest, timeout):
    try:
      data = self.incoming.read(len(dest), timeout=max(1, int((timeout if timeout is not None else 5) * 1000)))
      dest[:len(data)] = data.tobytes()
      return len(data)
    except self.usb.core.USBTimeoutError:
      return 0
    except self.usb.core.USBError as error:
      raise LinkError(str(error)) from error

  def close(self):
    self.usb.util.release_interface(self.device, self.interface)
    self.usb.util.dispose_resources(self.device)
