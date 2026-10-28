import React, { useState, useEffect, useRef } from 'react';
import { QrCode, X, CheckCircle, AlertCircle, Camera, Keyboard, Loader2, SwitchCamera } from 'lucide-react';
import jsQR from 'jsqr';
import api from '../../lib/api';

const BarcodeDetectorApi = typeof window !== 'undefined' ? (window.BarcodeDetector || null) : null;

// How long to wait for the OS permission handshake / camera hardware before
// giving up. getUserMedia can hang indefinitely if a device or another app is
// holding the camera, which would otherwise leave the UI stuck on "Starting…".
const CAMERA_TIMEOUT_MS = 12000;

const getCameraSupport = () => {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: 'Camera access requires a secure (HTTPS) connection and a supported browser.' };
  }
  return { ok: true };
};

const getUserMediaWithTimeout = (constraints, timeoutMs) => {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(Object.assign(new Error('Camera did not respond in time.'), { name: 'TimeoutError' }));
    }, timeoutMs);
    navigator.mediaDevices
      .getUserMedia(constraints)
      .then((stream) => { clearTimeout(timer); resolve(stream); })
      .catch((err) => { clearTimeout(timer); reject(err); });
  });
};

const QRScanner = ({ onClose, onScan }) => {
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [manualCode, setManualCode] = useState('');
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraStarting, setCameraStarting] = useState(false);
  const [frameReady, setFrameReady] = useState(false);
  const [cameraError, setCameraError] = useState('');
  const [cameraNotice, setCameraNotice] = useState('');
  const [facingMode, setFacingMode] = useState('environment');
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const rafRef = useRef(null);
  const scanningRef = useRef(false);
  const canvasRef = useRef(null);
  const unmountedRef = useRef(false);

  const stopCamera = () => {
    scanningRef.current = false;
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (streamRef.current) {
      // Explicitly stop every track to release the OS camera hardware;
      // otherwise the device stays locked and the next start hangs.
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.onloadedmetadata = null;
      videoRef.current.srcObject = null;
    }
    setFrameReady(false);
    setCameraOn(false);
  };

  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      stopCamera();
    };
  }, []);

  // Attach the stream only AFTER React has committed the <video> to the DOM.
  // Previously the stream was wired up in the same tick as setCameraOn(true),
  // when videoRef.current was still null, so srcObject was never set and the
  // preview stayed black. Keying this effect on cameraOn guarantees the element
  // exists and appears as soon as the first frame paints.
  useEffect(() => {
    if (!cameraOn) return;
    const video = videoRef.current;
    const stream = streamRef.current;
    if (!video || !stream) return;

    video.setAttribute('playsinline', 'true');
    video.setAttribute('webkit-playsinline', 'true');
    video.muted = true;
    video.srcObject = stream;

    let cancelled = false;
    let begun = false;
    const begin = () => {
      if (cancelled || begun || unmountedRef.current || !streamRef.current) return;
      begun = true;
      // play() resolves once playback has actually started; only then is there
      // a frame to decode, so the scan loop never spins on a black frame.
      video.play().then(() => {
        if (cancelled || unmountedRef.current || !streamRef.current) return;
        setFrameReady(true);
        scanLoop(video);
      }).catch(() => {
        // Autoplay can be rejected until the stream paints; retry once shortly.
        setTimeout(() => {
          if (cancelled || unmountedRef.current || !streamRef.current) return;
          setFrameReady(true);
          scanLoop(video);
        }, 250);
      });
    };

    if (video.readyState >= 2) {
      begin();
    } else {
      video.onloadedmetadata = begin;
      // Safety net: some browsers resolve frames without firing
      // loadedmetadata for MediaStream sources.
      video.oncanplay = begin;
    }

    return () => {
      cancelled = true;
      video.onloadedmetadata = null;
      video.oncanplay = null;
    };
  }, [cameraOn]);

  const extractToken = (raw) => {
    // The QR encodes the raw token, but may be wrapped in a URL
    const text = String(raw || '').trim();
    const match = text.match(/([A-Za-z0-9_-]{20,})/);
    return match ? match[1] : text;
  };

  const submitScan = async (token) => {
    const clean = extractToken(token);
    if (!clean) {
      setError('Invalid QR code. Please try again.');
      return;
    }
    setScanning(true);
    setError('');
    try {
      const res = await api.post('/attendance/scan/', { token: clean });
      const data = res.data?.data ?? res.data;
      if (data?.success || res.status === 201) {
        setResult({
          success: true,
          message: data?.message || 'Attendance recorded.',
          time: new Date().toLocaleTimeString(),
        });
        if (onScan) onScan({ success: true, record: data });
        stopCamera();
        if (data?.station_qr?.token) onClose();
      } else {
        setError(data?.message || 'Scan failed.');
        if (onScan) onScan({ success: false });
      }
    } catch (err) {
      const e = err.response?.data?.error;
      setError(e?.message || err.response?.data?.message || 'Scan failed. Please try again.');
      if (onScan) onScan({ success: false });
    } finally {
      setScanning(false);
    }
  };

  // Decode a single frame. Prefer the native BarcodeDetector (fast, hardware
  // accelerated) and fall back to jsQR, which works everywhere including
  // iOS Safari, Firefox and Edge where BarcodeDetector is unavailable.
  const decodeFrame = async (video) => {
    if (BarcodeDetectorApi) {
      try {
        const detector = new BarcodeDetectorApi({ formats: ['qr_code'] });
        const codes = await detector.detect(video);
        if (codes.length > 0) return codes[0].rawValue;
      } catch {
        // fall through to jsQR
      }
    }
    // jsQR needs a canvas snapshot of the current video frame.
    const canvas = canvasRef.current || document.createElement('canvas');
    canvasRef.current = canvas;
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) return null;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, w, h);
    const imageData = ctx.getImageData(0, 0, w, h);
    const code = jsQR(imageData.data, imageData.width, imageData.height, {
      inversionAttempts: 'dontInvert',
    });
    return code?.data || null;
  };

  const scanLoop = (video) => {
    scanningRef.current = true;
    const tick = async () => {
      if (!scanningRef.current) return;
      try {
        const value = await decodeFrame(video);
        if (value) {
          scanningRef.current = false;
          stopCamera();
          await submitScan(value);
          return;
        }
      } catch {
        // keep scanning
      }
      if (scanningRef.current) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  };

  const startCamera = async (mode = facingMode) => {
    setCameraError('');
    setCameraNotice('');

    const support = getCameraSupport();
    if (!support.ok) {
      setCameraError(support.reason + ' Use the code entry below.');
      return;
    }

    if (!BarcodeDetectorApi) {
      // No native decoder, but jsQR covers these browsers, so continue and
      // still request the camera instead of refusing outright.
      setCameraNotice('Using built-in scanner for this browser.');
    }

    // Ask for a modest resolution: enough to resolve a QR code, cheap to
    // decode and fast to negotiate. Over-tight constraints make some phones
    // take seconds to return a stream (or fall through the fallback chain).
    // Try requested facing mode first, then fall back gracefully.
    const attempts = [
      { video: { facingMode: { exact: mode }, width: { ideal: 1280 }, height: { ideal: 720 } } },
      { video: { facingMode: { ideal: mode }, width: { ideal: 1280 }, height: { ideal: 720 } } },
      { video: { facingMode: { ideal: mode === 'environment' ? 'user' : 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } } },
      { video: { facingMode: { ideal: mode } } },
      { video: true },
    ];

    setCameraStarting(true);
    let stream = null;
    let lastErr = null;
    for (const constraints of attempts) {
      try {
        stream = await getUserMediaWithTimeout(constraints, CAMERA_TIMEOUT_MS);
        break;
      } catch (err) {
        lastErr = err;
        // Hard stops: another constraint attempt cannot fix these.
        if (['NotAllowedError', 'SecurityError', 'NotFoundError', 'NotReadableError', 'TimeoutError'].includes(err?.name)) {
          break;
        }
      }
    }
    if (unmountedRef.current) {
      // Component closed while waiting for the camera: release immediately.
      if (stream) stream.getTracks().forEach(t => t.stop());
      return;
    }
    setCameraStarting(false);

    if (!stream) {
      const name = lastErr?.name;
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setCameraError('Camera permission was denied. Allow camera access for this site in your browser settings, then try again — or use the code entry below.');
      } else if (name === 'NotReadableError' || name === 'TrackStartError') {
        setCameraError('Your camera is already in use by another app or browser tab. Close it and try again — or use the code entry below.');
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        setCameraError('No usable camera was found on this device. Use the code entry below.');
      } else if (name === 'TimeoutError') {
        setCameraError('The camera is taking too long to start. Make sure no other app is using it, then try again — or use the code entry below.');
      } else {
        setCameraError('Could not access the camera: ' + (lastErr?.message || 'unknown error') + '. Use the code entry below.');
      }
      return;
    }

    // Store the stream and switch the UI to the video view. The effect above
    // wires srcObject/play()/scan-loop once the <video> is actually mounted.
    streamRef.current = stream;
    scanningRef.current = true;
    setCameraOn(true);
  };

  const switchCamera = async () => {
    if (cameraStarting) return;
    const newMode = facingMode === 'environment' ? 'user' : 'environment';
    setFacingMode(newMode);
    if (cameraOn) {
      stopCamera();
      // Small delay to ensure tracks are released before requesting new stream
      await new Promise((r) => setTimeout(r, 150));
      await startCamera(newMode);
    }
  };

  const handleManualSubmit = (e) => {
    e.preventDefault();
    if (!manualCode) {
      setError('Please enter the attendance code');
      return;
    }
    submitScan(manualCode);
    setManualCode('');
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="fet-card bg-white rounded-2xl shadow-modal max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-bold text-text-primary">Scan QR Code</h3>
          <div className="flex items-center gap-1">
            {cameraOn && (
              <button
                onClick={switchCamera}
                disabled={cameraStarting}
                className="p-1.5 hover:bg-page-bg rounded-lg disabled:opacity-60"
                aria-label="Switch camera"
                title="Switch camera"
              >
                <SwitchCamera size={22} className="text-text-secondary" />
              </button>
            )}
            <button onClick={() => { stopCamera(); onClose(); }} className="p-1 hover:bg-page-bg rounded-lg">
              <X size={24} className="text-text-secondary" />
            </button>
          </div>
        </div>

        {result?.success ? (
          <div className="text-center py-6">
            <CheckCircle size={64} className="mx-auto text-success mb-4" />
            <h4 className="text-xl font-bold text-success">Attendance Recorded</h4>
            <p className="text-text-secondary mt-2">{result.message}</p>
            <p className="text-text-secondary">Time: {result.time}</p>
            <button
              onClick={() => { stopCamera(); onClose(); }}
              className="mt-4 fet-btn-primary"
            >
              Done
            </button>
          </div>
        ) : (
          <>
            {cameraOn && (
              <div className="rounded-xl overflow-hidden bg-black relative">
                <video ref={videoRef} className="w-full h-64 object-cover" playsInline muted autoPlay />
                {!frameReady && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70 text-white">
                    <Loader2 size={32} className="animate-spin mb-2" />
                    <p className="text-xs">Starting camera preview…</p>
                  </div>
                )}
                <div className="absolute inset-0 border-2 border-primary rounded-xl pointer-events-none overlay-frame" />
                <p className="absolute bottom-2 left-0 right-0 text-center text-white text-xs bg-black/50 py-1">
                  {scanning ? 'Recording attendance...' : frameReady ? 'Point camera at the QR code' : 'Preparing camera…'}
                </p>
              </div>
            )}

            {!cameraOn && (
              <div className="border-2 border-dashed border-border-default rounded-xl p-8 text-center">
                {cameraError ? (
                  <div>
                    <AlertCircle size={40} className="mx-auto text-warning mb-2" />
                    <p className="text-sm text-text-secondary">{cameraError}</p>
                  </div>
                ) : cameraStarting ? (
                  <div>
                    <Loader2 size={64} className="mx-auto text-primary animate-spin" />
                    <p className="text-text-secondary mt-2">Starting camera…</p>
                    <p className="text-xs text-text-secondary mt-1">
                      If prompted, allow camera access for this site.
                    </p>
                  </div>
                ) : (
                  <div>
                    <QrCode size={64} className="mx-auto text-primary" />
                    <p className="text-text-secondary mt-2">Use your camera to scan the QR code</p>
                    {cameraNotice && (
                      <p className="text-xs text-text-secondary mt-1">{cameraNotice}</p>
                    )}
                  </div>
                )}
                <button
                  onClick={startCamera}
                  disabled={scanning || cameraStarting}
                  className="mt-4 fet-btn-primary flex items-center gap-2 mx-auto disabled:opacity-60"
                >
                  {cameraStarting ? <Loader2 size={18} className="animate-spin" /> : <Camera size={18} />}
                  {cameraStarting ? 'Starting…' : 'Start Camera'}
                </button>
              </div>
            )}

            <div className="mt-4">
              <p className="text-sm text-text-secondary text-center mb-2 flex items-center justify-center gap-1">
                <Keyboard size={14} /> OR enter the code shown under the QR
              </p>
              <form onSubmit={handleManualSubmit} className="flex gap-2">
                <input
                  type="text"
                  value={manualCode}
                  onChange={(e) => setManualCode(e.target.value)}
                  placeholder="Enter attendance code"
                  className="flex-1 fet-input uppercase"
                />
                <button
                  type="submit"
                  disabled={scanning}
                  className="fet-btn-primary"
                >
                  {scanning ? 'Checking...' : 'Submit'}
                </button>
              </form>
            </div>

            {error && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-xl text-danger text-sm flex items-center gap-2">
                <AlertCircle size={18} />
                {error}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default QRScanner;