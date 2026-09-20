import React from 'react';

interface StatusBadgeProps {
  status: string | null | undefined;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, className = '' }) => {
  const normStatus = (status || 'NO_DATA').toUpperCase();

  let styleClass = 'stale';
  let indicator = '○';

  switch (normStatus) {
    case 'CONNECTED':
    case 'ONLINE':
    case 'FRESH':
    case 'HEALTHY':
    case 'ACTIVE':
    case 'EXECUTED':
      styleClass = 'connected';
      indicator = '●';
      break;

    case 'DISCONNECTED':
    case 'OFFLINE':
    case 'ERROR':
    case 'REJECTED':
    case 'CRITICAL':
    case 'FAILED':
      styleClass = 'disconnected';
      indicator = '✕';
      break;

    case 'AGING':
    case 'WARNING':
    case 'LIMITED':
    case 'SUSPECTED':
    case 'MEDIUM':
      styleClass = 'aging';
      indicator = '▲';
      break;

    case 'NOT_CONFIGURED':
    case 'NOT_CONNECTED':
    case 'NO_DATA':
    case 'UNAVAILABLE':
    case 'STALE':
    default:
      styleClass = 'stale';
      indicator = '○';
      break;
  }

  return (
    <span className={`status-badge ${styleClass} ${className}`}>
      <span aria-hidden="true" style={{ fontSize: '0.8em' }}>{indicator}</span>
      <span>{normStatus.replace(/_/g, ' ')}</span>
    </span>
  );
};
