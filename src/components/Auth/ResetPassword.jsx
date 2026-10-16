import React, { useMemo, useState } from 'react';
import { Eye, EyeOff, ShieldCheck, ArrowLeft, GraduationCap, KeyRound } from 'lucide-react';
import { authApi } from '../../lib/auth';
import { errorMessage } from '../../lib/enrollment';

const ResetPassword = ({ email: initialEmail = '', onBack, onDone }) => {
  const urlEmail = useMemo(
    () => new URLSearchParams(window.location.search).get('email') || '',
    [],
  );

  const [email, setEmail] = useState(initialEmail || urlEmail);
  const [otp, setOtp] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const value = email.trim().toLowerCase();
    if (!value) {
      setError('Please enter your email address.');
      return;
    }
    if (!/^\d{6}$/.test(otp.trim())) {
      setError('Enter the 6-digit code from your email.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }

    setIsLoading(true);
    try {
      await authApi.confirmReset({ email: value, otp: otp.trim(), new_password: password });
      setDone(true);
      setPassword('');
      setConfirm('');
      setOtp('');
    } catch (err) {
      setError(errorMessage(err, 'That code is invalid or has expired. Request a new one.'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleResend = async () => {
    setError('');
    setNotice('');
    const value = email.trim().toLowerCase();
    if (!value) {
      setError('Please enter your email address.');
      return;
    }
    setIsResending(true);
    try {
      await authApi.requestOtp({ email: value });
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
            <h2 className="text-[28px] font-bold text-text-primary leading-tight">Enter reset code</h2>
            <p className="text-[14px] text-text-secondary mt-1.5">
              Type the 6-digit code we emailed you, then choose a new password.
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

          {done ? (
            <div className="bg-green-50 border border-green-200 text-green-800 px-4 py-4 rounded-xl text-[13px] mb-5">
              <div className="flex items-start gap-2">
                <ShieldCheck size={18} className="mt-0.5 shrink-0" />
                <p>Your password was reset. You can now sign in with your new password.</p>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="email" className="fet-label">University email</label>
                <input
                  id="email"
                  type="email"
                  placeholder="e.g., name@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="fet-input"
                  autoComplete="email"
                  required
                />
              </div>

              <div>
                <label htmlFor="otp" className="fet-label">6-digit code</label>
                <input
                  id="otp"
                  type="text"
                  inputMode="numeric"
                  placeholder="000000"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  className="fet-input text-center text-[20px] tracking-[10px] font-bold"
                  autoComplete="one-time-code"
                  maxLength={6}
                  required
                />
              </div>

              <div>
                <label htmlFor="new-password" className="fet-label">New password</label>
                <div className="relative">
                  <input
                    id="new-password"
                    type={showPassword ? 'text' : 'password'}
                    placeholder="At least 8 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="fet-input pr-11"
                    autoComplete="new-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-text-secondary hover:text-text-primary transition-colors"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </div>

              <div>
                <label htmlFor="confirm-password" className="fet-label">Confirm new password</label>
                <input
                  id="confirm-password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Re-enter your password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="fet-input"
                  autoComplete="new-password"
                  required
                />
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="fet-btn-primary w-full py-3 text-[14px] disabled:opacity-60"
              >
                {isLoading ? (
                  <div className="flex items-center gap-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                    Updating...
                  </div>
                ) : (
                  'Reset password'
                )}
              </button>

              <button
                type="button"
                onClick={handleResend}
                disabled={isResending}
                className="flex items-center gap-1.5 mx-auto text-[13px] text-primary font-semibold hover:opacity-80 transition-opacity disabled:opacity-60"
              >
                <KeyRound size={14} />
                {isResending ? 'Sending a new code...' : 'Resend code'}
              </button>
            </form>
          )}

          <button
            type="button"
            onClick={done ? onDone : onBack}
            className="flex items-center gap-1.5 mx-auto mt-6 text-[13px] text-primary font-semibold hover:opacity-80 transition-opacity"
          >
            <ArrowLeft size={14} />
            Back to sign in
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
            Your new password takes effect immediately, and every other device is signed out.
          </p>
        </div>
      </div>
    </div>
  );
};

export default ResetPassword;
