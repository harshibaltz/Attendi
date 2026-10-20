import React, { useState, useEffect } from 'react';
import { Mail, Lock, Eye, EyeOff, User, UserPlus, ArrowLeft, Building, GraduationCap, BookOpen, BadgeCheck } from 'lucide-react';
import { authApi } from '../../lib/auth';
import { academicsApi } from '../../lib/academics';

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

const formatServerError = (errorData) => {
  if (!errorData) return 'Unable to create account. Please try again.';

  if (typeof errorData === 'string') return errorData;

  if (Array.isArray(errorData)) {
    return errorData.map((item) => formatServerError(item)).join(' ');
  }

  if (typeof errorData === 'object') {
    const messages = [];
    Object.values(errorData).forEach((value) => {
      if (Array.isArray(value)) {
        value.forEach((item) => messages.push(formatServerError(item)));
      } else if (typeof value === 'string') {
        messages.push(value);
      } else if (value && typeof value === 'object') {
        messages.push(formatServerError(value));
      }
    });

    const clean = messages.filter(Boolean).map((item) => item.trim()).filter(Boolean);
    return clean[0] || 'Unable to create account. Please try again.';
  }

  return 'Unable to create account. Please try again.';
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

  useEffect(() => {
    const loadDepartments = async () => {
      try {
        const depts = await academicsApi.publicDepartments();
        if (Array.isArray(depts) && depts.length > 0) {
          setDepartments(depts);
          return;
        }
      } catch {
        // Fall back to local cache if the API is unavailable.
      }

      let depts = JSON.parse(localStorage.getItem('fet_departments') || '[]');
      if (!Array.isArray(depts) || depts.length === 0) {
        depts = [
          { id: '1', name: 'Computer Engineering', code: 'CE' },
          { id: '2', name: 'Civil Engineering', code: 'CVE' },
          { id: '3', name: 'Chemical & Petroleum Engineering', code: 'CHE' },
          { id: '4', name: 'Electrical & Electronic Engineering', code: 'EE' },
          { id: '5', name: 'Mechanical & Industrial Engineering', code: 'ME' },
        ];
        localStorage.setItem('fet_departments', JSON.stringify(depts));
      }
      setDepartments(depts);
    };

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
        setError('Personal email is required for students.');
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
      setError('Please select a valid department.');
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
      setSuccess(response.data?.message || 'Account created successfully. Please sign in.');
      setTimeout(() => {
        setIsLoading(false);
        onSwitchToLogin();
      }, 1200);
    } catch (err) {
      setIsLoading(false);
      const message = formatServerError(err.response?.data || err.message);
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
                <Building className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                <select name="department" value={formData.department} onChange={handleChange}
                  className={`${inputBase} pl-10`} required>
                  <option value="">-- Select Department --</option>
                  {departments.length > 0 ? (
                    departments.map(dept => (
                      <option key={dept.id} value={dept.id}>{dept.name} ({dept.code || 'Dept'})</option>
                    ))
                  ) : (
                    <option value="" disabled>Loading departments...</option>
                  )}
                </select>
              </div>
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
                    <GraduationCap className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-secondary" size={16} />
                    <select name="level" value={formData.level} onChange={handleChange} className={`${inputBase} pl-10`} required>
                      <option value="">Select Level</option>
                      <option value="200">200 Level</option>
                      <option value="300">300 Level</option>
                      <option value="400">400 Level</option>
                      <option value="500">500 Level</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className={labelBase}>Personal Email *</label>
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
