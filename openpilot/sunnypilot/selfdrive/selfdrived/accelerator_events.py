"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The accelerator's place in selfdrived. Two things live here upstream: what
selfdrived must not count as a fault, and the onroad events for a large model
that joins mid-drive rather than being loaded before the first modelV2.

Only the first is here. The second needs `OnroadEventSP.EventName` to carry
`bigModelAvailable` and `bigModelLinkLost`, and this branch's cereal has
neither (`bigModelAvailableDEPRECATED @3` on `ModelDataV2SP` is a different
field, and `bigModelReady @25` is the only accelerator event name left), so
the offer and hand-back alerts would need a schema change and regenerated
bindings. The accelerator state the UI and those alerts read,
`ModelDataV2SP.acceleratorState`, is already published by both modelds.
"""
from openpilot.sunnypilot import jetlink_adapter


class AcceleratorEvents:
  # An accelerator is optional: its daemon exiting costs the big model, never
  # engagement. manager does not restart a process that died, so without this
  # a dead link owner was processNotRunning, NO_ENTRY until a reboot
  OPTIONAL_PROCESSES = frozenset({jetlink_adapter.OWNER})
