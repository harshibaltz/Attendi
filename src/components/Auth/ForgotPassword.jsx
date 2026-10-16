import React, { useState } from 'react';
import { ArrowRight, ArrowLeft, GraduationCap, MailCheck } from 'lucide-react';
import { authApi } from '../../lib/auth';
import { errorMessage } from '../../lib/enrollment';

const ForgotPassword = ({ onBack, onCodeSent }) => {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const value = email.trim().toLowerCase();
    if (!value) {
      setError('Please enter your email address.');
      return;
    }

    setIsLoading(true);
    try {
      await authApi.requestOtp({ email: value });
      // The server always answers the same way, whether or not the account
      // exists, so we move to the code screen either way.
      onCodeSent(value);
    } catch (err) {
      setError(errorMessage(err, 'Could not send the code. Please try again.'));
    } finally {
      setIsLoading(false);
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
            <h2 className="text-[28px] font-bold text-text-primary leading-tight">Forgot password?</h2>
            <p className="text-[14px] text-text-secondary mt-1.5">
              Enter your university email and we&apos;ll send you a 6-digit code to reset your password.
            </p>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-[13px] mb-5 font-medium">
              {error}
            </div>
          )}

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

            <button
              type="submit"
              disabled={isLoading}
              className="fet-btn-primary w-full py-3 text-[14px] disabled:opacity-60"
            >
              {isLoading ? (
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  Sending...
                </div>
              ) : (
                <>
                  Send code
                  <ArrowRight size={16} />
                </>
              )}
            </button>

            <p className="flex items-start gap-2 text-[12px] text-text-secondary">
              <MailCheck size={15} className="mt-0.5 shrink-0" />
              Check your inbox and spam folder. The code expires in 10 minutes.
            </p>
          </form>

          <button
            type="button"
            onClick={onBack}
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
            Reset access to your account securely with a one-time code sent to your email.
          </p>
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;
