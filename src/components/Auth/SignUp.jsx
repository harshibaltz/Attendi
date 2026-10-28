import React, { useState, useEffect } from 'react';
import { Mail, Lock, Eye, EyeOff, User, UserPlus, ArrowLeft, Building, GraduationCap, BookOpen, BadgeCheck, ChevronDown } from 'lucide-react';
import { authApi } from '../../lib/auth';
import { academicsApi } from '../../lib/academics';
import { getDisplayName, normalizeUser } from '../../lib/profile';

const normalizeFullName = (value) => {
  const trimmed = (value || '').trim();
  if (!trimmed) return { first_name: '', last_name: '' };

  const parts = trimmed.split(/\s+/);
  if (parts.length === 1) {
    return { first_name: parts[0], last_name: 'User' };
  }

  return {
    first_name: parts[0],
    last_name: parts.slice(1).join(' '),
  };
};

const GENERIC_ERRORS = new Set([
  'the request could not be completed.',
  'unable to create account. please try again.',
]);

const collectMessages = (value, out = []) => {
  if (!value) return out;
  if (typeof value === 'string') {
    const text = value.trim();
    // Skip machine codes like "VALIDATION_ERROR" - they mean nothing to a user.
    if (text && !/^[A-Z0-9_]+$/.test(text)) out.push(text);
    return out;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectMessages(item, out));
    return out;
  }
  if (typeof value === 'object') {
    // Prefer per-field detail messages over the envelope's generic message.
    if (value.details) collectMessages(value.details, out);
    if (value.error) collectMessages(value.error, out);
    if (value.message) collectMessages(value.message, out);
    Object.entries(value).forEach(([key, item]) => {
      if (['details', 'error', 'message', 'success', 'code'].includes(key)) return;
      collectMessages(item, out);
    });
  }
  return out;
};

const formatServerError = (errorData) => {
  if (!errorData) return 'Unable to create account. Please try again.';
  const messages = collectMessages(errorData)
    .filter((message) => !GENERIC_ERRORS.has(message.toLowerCase().replace(/\s+/g, ' ')));
  return messages[0] || 'Some details are not valid. Please check the form and try again.';
};

const SignUp = ({ onSignUp, onSwitchToLogin }) => {
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [departments, setDepartments] = useState([]);
  const [formData, setFormData] = useState({
    fullName: '',
    email: '',
    password: '',
    confirmPassword: '',
    role: 'student',
    department: '',
    level: '',
    matricule: '',
    personalEmail: '',
    staffNumber: '',
  });
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [departmentsError, setDepartmentsError] = useState('');
  const [loadingDepartments, setLoadingDepartments] = useState(true);

  // Only real departments (UUID ids) may be offered. A fabricated list is
  // worse than none: the backend rejects unknown ids with a validation error,
  // and students cannot tell what went wrong.
  const loadDepartments = async () => {
    setLoadingDepartments(true);
    setDepartmentsError('');
    try {
      const depts = await academicsApi.publicDepartments();
      const valid = Array.isArray(depts)
        ? depts.filter((dept) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(dept?.id || '')))
        : [];
      if (valid.length > 0) {
        setDepartments(valid);
        localStorage.setItem('fet_departments', JSON.stringify(valid));
        setLoadingDepartments(false);
        return;
      }
      setDepartmentsError('Departments could not be loaded. Please check your connection and try again.');
    } catch {
      setDepartmentsError('Departments could not be loaded. Please check your connection and try again.');
    }

    // A previously cached real list can bridge a brief outage.
    let cached = [];
    try {
      cached = JSON.parse(localStorage.getItem('fet_departments') || '[]');
    } catch {
      cached = [];
    }
    const validCached = Array.isArray(cached)
      ? cached.filter((dept) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(dept?.id || '')))
      : [];
    setDepartments(validCached);
    setLoadingDepartments(false);
  };

  useEffect(() => {
    loadDepartments();
  }, []);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    setSuccess('');

    const email = formData.email.trim().toLowerCase();
    const password = formData.password;
    const fullName = formData.fullName.trim();

    if (!fullName || !email || !password || !formData.department) {
      setError('Please fill in all required fields.');
      setIsLoading(false);
      return;
    }

    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setError('Please enter a valid email address.');
      setIsLoading(false);
      return;
    }

    if (password !== formData.confirmPassword) {
      setError('Passwords do not match.');
      setIsLoading(false);
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters long.');
      setIsLoading(false);
      return;
    }

    if (formData.role === 'student') {
      if (!formData.matricule.trim()) {
        setError('Matricule number is required for students.');
        setIsLoading(false);
        return;
      }
      if (!formData.level) {
        setError('Please select your level.');
        setIsLoading(false);
        return;
      }
      if (!formData.personalEmail.trim()) {
        setError('Institutional email is required for students.');
        setIsLoading(false);
        return;
      }
    }

    if (formData.role === 'lecturer' && !formData.staffNumber.trim()) {
      setError('Staff number is required for lecturers.');
      setIsLoading(false);
      return;
    }

    const selectedDept = departments.find((dept) => {
      if (typeof dept.id === 'string' && dept.id === formData.department) return true;
      if (dept.name && dept.name === formData.department) return true;
      return false;
    });

    if (!selectedDept) {
      setError(departments.length === 0
        ? 'Departments could not be loaded. Please retry and select your department.'
        : 'Please select a valid department.');
      setIsLoading(false);
      return;
    }

    const { first_name, last_name } = normalizeFullName(fullName);

    const payload = {
      email,
      password,
      password_confirm: formData.confirmPassword,
      first_name,
      last_name,
      department: selectedDept.id,
      role: formData.role.toUpperCase(),
      ...(formData.role === 'student' && {
        matricule: formData.matricule.trim().toUpperCase(),
        level: formData.level,
        personal_email: formData.personalEmail.trim().toLowerCase(),
      }),
      ...(formData.role === 'lecturer' && {
        staff_number: formData.staffNumber.trim(),
      }),
    };

    try {
      const response = await authApi.selfRegister(payload);
      const created = normalizeUser(
        response.data?.data ?? response.data ?? {
          ...payload,
          full_name: `${first_name} ${last_name}`.trim(),
        }
      );

      // Registration now starts a real cookie session. Verify the browser kept
      // it before entering the app, exactly like the login flow does.
      try {
        const me = await authApi.me();
        const verified = me.data?.data ?? me.data;
        if (!verified) throw new Error('empty session');
        created.role = verified.role || created.role;
        created.fullName = getDisplayName(verified, '') || created.fullName;
      } catch {
        setIsLoading(false);
        setError(
          'Your account was created, but the session could not be started. ' +
            'Please sign in with your new credentials.'
        );
        return;
      }

      setIsLoading(false);
      setSuccess('Account created. Taking you to your dashboard...');
      onSignUp(created);
    } catch (err) {
      setIsLoading(false);
      const message = err.response
        ? formatServerError(err.response.data)
        : 'Network problem. Check your connection and try again.';
      setError(message);
    }
  };

  const inputBase = "fet-input";
  const labelBase = "fet-label";

  return (
    <div className="min-h-screen flex">
      {/* Left: Form */}
      <div className="flex-1 flex items-center justify-center p-6 fet-auth-panel">
        <div className="w-full max-w-[420px]">
          <button onClick={onSwitchToLogin} className="flex items-center gap-2 text-text-secondary hover:text-text-primary mb-8 transition-colors text-[13px] font-medium">
            <ArrowLeft size={16} /> Back to Login
          </button>

          <div className="mb-8">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-4" style={{ backgroundColor: '#3F35B5' }}>
              <UserPlus size={22} className="text-white" />
            </div>
            <h1 className="text-[26px] font-bold text-text-primary">Create Account</h1>
            <p className="text-[14px] text-text-secondary mt-1">Join the FET Management Platform</p>
          </div>

          {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-[13px] mb-5 font-medium">{error}</div>}
          {success && <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-xl text-[13px] mb-5 whitespace-pre-line font-medium">{success}</div>}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className={labelBase}>Full Name *</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                <input type="text" name="fullName" value={formData.fullName} onChange={handleChange}
                  placeholder="e.g., John Doe" className={`${inputBase} pl-10`} required />
              </div>
            </div>

            <div>
              <label className={labelBase}>Email *</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                <input type="email" name="email" value={formData.email} onChange={handleChange}
                  placeholder="you@domain.com" className={`${inputBase} pl-10`} required />
              </div>
            </div>

            <div>
              <label className={labelBase}>I am a *</label>
              <div className="grid grid-cols-2 gap-3">
                {['student', 'lecturer'].map((role) => (
                  <button key={role} type="button" onClick={() => setFormData(prev => ({ ...prev, role }))}
                    className={`px-4 py-3 rounded-xl border-2 capitalize font-medium text-[13px] transition-all ${
                      formData.role === role
                        ? 'border-primary bg-primary-light text-primary'
                        : 'border-border-default hover:border-primary/40 text-text-secondary'
                    }`}>
                    {role}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className={labelBase}>Department *</label>
              <div className="relative">
                <Building className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary pointer-events-none" size={16} />
                <select name="department" value={formData.department} onChange={handleChange}
                  className={`${inputBase} pl-10 pr-9 appearance-none`} required disabled={loadingDepartments || departments.length === 0}>
                  <option value="">{loadingDepartments ? 'Loading departments...' : '-- Select Department --'}</option>
                  {departments.map(dept => (
                    <option key={dept.id} value={dept.id}>{dept.name} ({dept.code || 'Dept'})</option>
                  ))}
                </select>
                <ChevronDown className="absolute right-3 top-1/2 transform -translate-y-1/2 text-text-secondary pointer-events-none" size={16} />
              </div>
              {departmentsError && (
                <p className="mt-1 text-[12px] text-red-600">
                  {departmentsError}{' '}
                  <button type="button" onClick={loadDepartments} className="underline font-medium">Retry</button>
                </p>
              )}
            </div>

            {formData.role === 'student' && (
              <>
                <div>
                  <label className={labelBase}>Matricule Number *</label>
                  <div className="relative">
                    <BookOpen className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                    <input type="text" name="matricule" value={formData.matricule} onChange={handleChange}
                      placeholder="e.g., FE24A389" className={`${inputBase} pl-10 uppercase`} required />
                  </div>
                  <p className="text-[11px] text-text-secondary mt-1">Your unique student identification number</p>
                </div>
                <div>
                  <label className={labelBase}>Level *</label>
                  <div className="relative">
                    <GraduationCap className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary pointer-events-none" size={16} />
                    <select name="level" value={formData.level} onChange={handleChange} className={`${inputBase} pl-10 pr-9 appearance-none`} required>
                      <option value="">Select Level</option>
                      <option value="200">200 Level</option>
                      <option value="300">300 Level</option>
                      <option value="400">400 Level</option>
                      <option value="500">500 Level</option>
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 transform -translate-y-1/2 text-text-secondary pointer-events-none" size={16} />
                  </div>
                </div>
                <div>
                  <label className={labelBase}>Institutional Email *</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                    <input type="email" name="personalEmail" value={formData.personalEmail} onChange={handleChange}
                      placeholder="you@gmail.com" className={`${inputBase} pl-10`} required />
                  </div>
                </div>
              </>
            )}

            {formData.role === 'lecturer' && (
              <div>
                <label className={labelBase}>Staff Number *</label>
                <div className="relative">
                  <BadgeCheck className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                  <input type="text" name="staffNumber" value={formData.staffNumber} onChange={handleChange}
                    placeholder="e.g., STF0099" className={`${inputBase} pl-10 uppercase`} required />
                </div>
              </div>
            )}

            <div>
              <label className={labelBase}>Password * (min 8)</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                <input type={showPassword ? 'text' : 'password'} name="password" value={formData.password} onChange={handleChange}
                  className={`${inputBase} pl-10 pr-11`} required />
                <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-1/2 text-text-secondary hover:text-text-primary">
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <div>
              <label className={labelBase}>Confirm Password *</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                <input type={showConfirmPassword ? 'text' : 'password'} name="confirmPassword" value={formData.confirmPassword} onChange={handleChange}
                  className={`${inputBase} pl-10 pr-11`} required />
                <button type="button" onClick={() => setShowConfirmPassword(!showConfirmPassword)} className="absolute right-3 top-1/2 text-text-secondary hover:text-text-primary">
                  {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button type="submit" disabled={isLoading}
              className="fet-btn-primary w-full py-3 text-[14px] disabled:opacity-60 mt-2">
              {isLoading ? 'Creating account...' : 'Create Account'}
            </button>
          </form>

          <p className="text-center text-[13px] text-text-secondary mt-6">
            Already have an account? <button onClick={onSwitchToLogin} className="text-primary font-semibold hover:opacity-80">Sign in</button>
          </p>
        </div>
      </div>

      {/* Right: Visual Section */}
      <div className="hidden lg:flex flex-1 relative fet-tech-grid items-center justify-center">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-transparent"></div>
        <div className="relative z-10 text-center px-12 max-w-lg">
          <div className="w-20 h-20 rounded-2xl flex items-center justify-center mx-auto mb-8" style={{ backgroundColor: 'rgba(63,53,181,0.3)', border: '1px solid rgba(63,53,181,0.2)' }}>
            <GraduationCap size={36} className="text-white" />
          </div>
          <h2 className="text-[28px] font-bold text-white leading-tight mb-4">
            Join FET Platform
          </h2>
          <p className="text-[15px] text-white/50 leading-relaxed">
            Register as a student or lecturer to access the complete engineering management experience.
          </p>
        </div>
      </div>
    </div>
  );
};

export default SignUp;
