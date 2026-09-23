"""TRAFFICINTEL AI - Camera Stream & Device Provider

Validates RTSP and HTTP/ONVIF camera stream connectivity.
Never fabricates camera frames or video streams.
"""

import socket
import urllib.parse
from typing import Dict, Any, Tuple
import time
from app.providers.base import CameraProvider
from app.health.monitor import provider_monitor


class NetworkCameraAdapter(CameraProvider):
    """Adapter for verifying and interfacing with real IP cameras & RTSP streams."""

    def __init__(self, stream_url: str, timeout: float = 2.5):
        self.stream_url = stream_url
        self.timeout = timeout

    def test_connection(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Tests TCP handshake to the camera host and port specified in the URL."""
        try:
            parsed = urllib.parse.urlparse(self.stream_url)
            host = parsed.hostname
            if not host:
                return False, f"Invalid camera URL format: '{self.stream_url}'", {}

            port = parsed.port
            if not port:
                if parsed.scheme == "rtsp":
                    port = 554
                elif parsed.scheme == "https":
                    port = 443
                elif parsed.scheme == "http":
                    port = 80
                else:
                    port = 554

            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((host, port))
            latency = (time.time() - start_time) * 1000.0
            sock.close()

            provider_monitor.record(
                "camera:{}:{}".format(host, port), True, latency,
                kind="CAMERA", label="Camera {}:{}".format(host, port),
            )
            return True, f"Camera reachable at {host}:{port} ({latency:.1f}ms)", {
                "host": host,
                "port": port,
                "protocol": parsed.scheme.upper(),
                "latency_ms": round(latency, 1),
                "status": "CONNECTED"
            }
        except socket.timeout:
            return False, f"Connection timed out ({self.timeout}s) reaching camera host", {
                "status": "OFFLINE",
                "error": "TIMEOUT"
            }
        except ConnectionRefusedError:
            return False, f"Connection refused on camera port", {
                "status": "OFFLINE",
                "error": "CONNECTION_REFUSED"
            }
        except Exception as e:
            return False, f"Network error contacting camera: {str(e)}", {
                "status": "ERROR",
                "error": str(e)
            }

    def get_stream_info(self) -> Dict[str, Any]:
        """Reports what the reachability test actually established.

        A TCP handshake proves a host is listening. It negotiates no RTSP
        session, so it reveals nothing about codec, resolution or frame rate.
        Those fields stay null with an explicit reason rather than carrying
        typical-looking values that an operator would read as measured.
        """
        success, msg, details = self.test_connection()
        if not success:
            return {
                "stream_status": "OFFLINE",
                "fps": None,
                "resolution": None,
                "measurement_status": "NOT_MEASURED_HOST_UNREACHABLE",
                "message": msg,
                "details": details
            }
        return {
            "stream_status": "REACHABLE",
            "fps": None,
            "resolution": None,
            "measurement_status": "NOT_MEASURED_NO_RTSP_SESSION",
            "message": msg,
            "details": details
        }
