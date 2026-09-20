import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { Plus, X } from 'lucide-react';

export const Users: React.FC = () => {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState('OPERATOR');
  const [creating, setCreating] = useState(false);

  const loadUsers = async () => {
    try {
      const data = await api.getUsers();
      setUsers(data);
    } catch (err) {
      console.error('Failed to load users', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createUser({
        username,
        email,
        password,
        full_name: fullName,
        role,
      });
      setShowModal(false);
      setUsername('');
      setEmail('');
      setPassword('');
      setFullName('');
      loadUsers();
    } catch (err: any) {
      alert(`User creation error: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>Authorized Operator Roles & Access Control</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            Role-Based Access Control (ADMIN, ENGINEER, OPERATOR, AUDITOR) with audit verification.
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="its-btn its-btn-primary">
          <Plus size={16} />
          <span>Provision User</span>
        </button>
      </div>

      <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="its-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Full Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Created At</th>
              <th>Last Active</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '24px', color: 'var(--its-text-muted)' }}>
                  Loading authorized user accounts...
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '24px', color: 'var(--its-text-muted)' }}>
                  No operator accounts found.
                </td>
              </tr>
            ) : (
              users.map((u) => (
                <tr key={u.id}>
                  <td className="mono" style={{ fontWeight: 600, color: '#58a6ff' }}>{u.username}</td>
                  <td style={{ fontWeight: 500 }}>{u.full_name}</td>
                  <td style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)' }}>{u.email}</td>
                  <td>
                    <span
                      style={{
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        padding: '2px 6px',
                        borderRadius: '4px',
                        background: 'var(--its-bg-card)',
                        border: '1px solid var(--its-border-subtle)',
                      }}
                    >
                      {u.role}
                    </span>
                  </td>
                  <td><StatusBadge status={u.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                    {u.last_login ? new Date(u.last_login).toLocaleString() : 'Never'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '460px',
              background: 'var(--its-bg-surface)',
              border: '1px solid var(--its-border-subtle)',
              borderRadius: 'var(--radius-lg)',
              padding: '24px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>Provision Operator Account</h2>
              <button onClick={() => setShowModal(false)} style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreate}>
              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Username
                </label>
                <input type="text" className="its-input" value={username} onChange={(e) => setUsername(e.target.value)} required />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Full Legal / Operational Name
                </label>
                <input type="text" className="its-input" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                  Email Address
                </label>
                <input type="email" className="its-input" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>

              <div className="grid-2" style={{ marginBottom: '20px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                    Password
                  </label>
                  <input type="password" className="its-input" value={password} onChange={(e) => setPassword(e.target.value)} required />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', marginBottom: '4px' }}>
                    RBAC Role
                  </label>
                  <select className="its-select" value={role} onChange={(e) => setRole(e.target.value)}>
                    <option value="OPERATOR">Operator</option>
                    <option value="ENGINEER">Traffic Engineer</option>
                    <option value="ADMIN">Administrator</option>
                    <option value="AUDITOR">Auditor (Read-Only)</option>
                  </select>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="its-btn">Cancel</button>
                <button type="submit" className="its-btn its-btn-primary" disabled={creating}>
                  {creating ? 'Creating...' : 'Provision User'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
