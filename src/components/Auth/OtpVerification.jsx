import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, GraduationCap, RefreshCw } from 'lucide-react';
import { authApi } from '../../lib/auth';
import { errorMessage } from '../../lib/enrollment';

const OTP_TTL_SECONDS = 10 * 60;
const RESEND_SECONDS = 60;

const fmt = (total) => {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
};

const OtpVerification = ({ email, onVerified, onBack }) => {
  const [otp, setOtp] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [resendIn, setResendIn] = useState(RESEND_SECONDS);
  const [expiresIn, setExpiresIn] = useState(OTP_TTL_SECONDS);

  useEffect(() => {
    const timer = setInterval(() => {
      setResendIn((s) => (s > 0 ? s - 1 : 0));
      setExpiresIn((s) => (s > 0 ? s - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const expired = expiresIn <= 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setNotice('');

    if (!/^\d{6}$/.test(otp.trim())) {
      setError('Enter the 6-digit code from your email.');
      return;
    }
    if (expired) {
      setError('That code has expired. Request a new one.');
      return;
    }

    setIsLoading(true);
    try {
      await authApi.verifyOtp({ email, otp: otp.trim() });
      onVerified(otp.trim());
    } catch (err) {
      // Stay on this page so the code can be retried or resent.
      setError(errorMessage(err, 'That code is incorrect. Please try again.'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleResend = async () => {
    setError('');
    setNotice('');
    setIsResending(true);
    try {
      await authApi.requestOtp({ email });
      setOtp('');
      setResendIn(RESEND_SECONDS);
      setExpiresIn(OTP_TTL_SECONDS);
      setNotice('A new code is on its way. Check your inbox and spam folder.');
    } catch (err) {
      setError(errorMessage(err, 'Could not resend the code. Please try again.'));
    } finally {
      setIsResending(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      <div className="flex-1 flex items-center justify-center p-6 bg-white">
        <div className="w-full max-w-[400px]">
          <div className="flex items-center gap-3 mb-10">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ backgroundColor: '#3F35B5' }}>
              <span className="text-white font-bold text-lg">FET</span>
            </div>
            <div>
              <h1 className="text-[17px] font-bold text-text-primary leading-tight">FET Platform</h1>
              <p className="text-[11px] text-text-secondary font-medium">Engineering Management</p>
            </div>
          </div>

          <div className="mb-8">
            <h2 className="text-[28px] font-bold text-text-primary leading-tight">Enter your code</h2>
            <p className="text-[14px] text-text-secondary mt-1.5">
              We sent a 6-digit code to <span className="font-semibold text-text-primary">{email}</span>.
            </p>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-[13px] mb-5 font-medium">
              {error}
            </div>
          )}

          {notice && (
            <div className="bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-xl text-[13px] mb-5 font-medium">
              {notice}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="otp" className="fet-label">6-digit code</label>
                <span className={`text-[12px] font-medium ${expired ? 'text-red-600' : 'text-text-secondary'}`}>
                  {expired ? 'Code expired' : `Expires in ${fmt(expiresIn)}`}
                </span>
              </div>
              <input
                id="otp"
                type="text"
                inputMode="numeric"
                placeholder="000000"
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="fet-input text-center text-[22px] tracking-[10px] font-bold"
                autoComplete="one-time-code"
                maxLength={6}
                autoFocus
                required
              />
            </div>

            <button
              type="submit"
              disabled={isLoading || expired}
              className="fet-btn-primary w-full py-3 text-[14px] disabled:opacity-60"
            >
              {isLoading ? (
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  Verifying...
                </div>
              ) : (
                <>
                  Verify code
                  <ArrowRight size={16} />
                </>
              )}
            </button>

            <button
              type="button"
              onClick={handleResend}
              disabled={isResending || resendIn > 0}
              className="flex items-center gap-1.5 mx-auto text-[13px] text-primary font-semibold hover:opacity-80 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw size={14} />
              {isResending
                ? 'Sending a new code...'
                : resendIn > 0
                  ? `Resend code in ${resendIn}s`
                  : 'Resend code'}
            </button>
          </form>

          <button
            type="button"
            onClick={onBack}
            className="flex items-center gap-1.5 mx-auto mt-6 text-[13px] text-primary font-semibold hover:opacity-80 transition-opacity"
          >
            <ArrowLeft size={14} />
            Use a different email
          </button>
        </div>
      </div>

      <div className="hidden lg:flex flex-1 relative fet-tech-grid items-center justify-center">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-transparent"></div>
        <div className="relative z-10 text-center px-12 max-w-lg">
          <div className="w-20 h-20 rounded-2xl flex items-center justify-center mx-auto mb-8" style={{ backgroundColor: 'rgba(63,53,181,0.3)', border: '1px solid rgba(63,53,181,0.2)' }}>
            <GraduationCap size={36} className="text-white" />
          </div>
          <h2 className="text-[28px] font-bold text-white leading-tight mb-4">
            Faculty of Engineering<br />&amp; Technology
          </h2>
          <p className="text-[15px] text-white/50 leading-relaxed">
            Check your inbox for a 6-digit code. It stays valid for 10 minutes.
          </p>
        </div>
      </div>
    </div>
  );
};

export default OtpVerification;
