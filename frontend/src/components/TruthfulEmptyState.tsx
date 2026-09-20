import React from 'react';
import { AlertCircle, PlusCircle } from 'lucide-react';
import { Link } from 'react-router-dom';

interface TruthfulEmptyStateProps {
  title: string;
  description: string;
  actionText?: string;
  actionLink?: string;
  icon?: React.ReactNode;
}

export const TruthfulEmptyState: React.FC<TruthfulEmptyStateProps> = ({
  title,
  description,
  actionText,
  actionLink,
  icon,
}) => {
  return (
    <div
      style={{
        padding: '36px 24px',
        textAlign: 'center',
        background: 'var(--its-bg-surface)',
        border: '1px dashed var(--its-border-subtle)',
        borderRadius: 'var(--radius-lg)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        margin: '16px 0',
      }}
    >
      <div style={{ color: 'var(--its-text-muted)', marginBottom: '12px' }}>
        {icon || <AlertCircle size={36} />}
      </div>
      <h3
        style={{
          fontSize: 'var(--text-md)',
          fontWeight: 600,
          color: 'var(--its-text-primary)',
          marginBottom: '6px',
          letterSpacing: '0.02em',
        }}
      >
        {title}
      </h3>
      <p
        style={{
          fontSize: 'var(--text-sm)',
          color: 'var(--its-text-secondary)',
          maxWidth: '460px',
          marginBottom: actionText && actionLink ? '16px' : '0',
          lineHeight: 1.5,
        }}
      >
        {description}
      </p>

      {actionText && actionLink && (
        <Link
          to={actionLink}
          className="its-btn its-btn-primary"
          style={{ textDecoration: 'none' }}
        >
          <PlusCircle size={15} />
          <span>{actionText}</span>
        </Link>
      )}
    </div>
  );
};
