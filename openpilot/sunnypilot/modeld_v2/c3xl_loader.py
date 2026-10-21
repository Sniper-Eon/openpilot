import os
import threading
from collections.abc import Callable, MutableMapping

C3XL_MODEL_LOAD_TIMEOUT = 120
C3XL_TINYGRAD_CACHE_HOME = "/data/cache"


class ModelLoadError(RuntimeError):
  pass


def configure_default_device(comma_hardware: bool, environment: MutableMapping[str, str] = os.environ, *, c3xl: bool = False) -> None:
  """Select the stable C3XL tinygrad device/cache without probing USB GPUs."""
  if comma_hardware:
    environment.setdefault("DEV", "QCOM")
  if c3xl:
    environment.setdefault("XDG_CACHE_HOME", C3XL_TINYGRAD_CACHE_HOME)


def load_with_timeout[T](load: Callable[[], T], timeout: float) -> T:
  result: list[T] = []
  error: list[Exception] = []
  done = threading.Event()

  def run() -> None:
    try:
      result.append(load())
    except Exception as e:
      error.append(e)
    finally:
      done.set()

  threading.Thread(target=run, name="c3xl-model-loader", daemon=True).start()
  if not done.wait(timeout):
    raise TimeoutError(f"model load timed out after {timeout:g}s")
  if error:
    raise ModelLoadError(f"model load failed: {error[0]}") from error[0]
  return result[0]
