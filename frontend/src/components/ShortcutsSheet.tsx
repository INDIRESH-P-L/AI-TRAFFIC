import React, { useEffect } from 'react';
import { Keyboard, X } from 'lucide-react';

/**
 * Keyboard shortcut reference, opened with "?".
 *
 * Every shortcut listed here is actually bound in Layout. A cheat sheet that
 * advertises keys that do nothing is worse than none.
 */

export const SHORTCUTS: Array<{ group: string; items: Array<[string, string]> }> = [
  {
    group: 'Global',
    items: [
      ['Ctrl / ⌘ + K', 'Open the command palette'],
      ['/', 'Open the command palette (when not typing)'],
      ['?', 'Show this shortcut sheet'],
      ['Esc', 'Close the open drawer, dialog or palette'],
    ],
  },
  {
    group: 'Console',
    items: [
      ['g then d', 'Go to Dashboard'],
      ['g then m', 'Go to Live GIS Map'],
      ['g then i', 'Go to Incident Console'],
      ['g then s', 'Go to Settings & Health'],
    ],
  },
  {
    group: 'Display',
    items: [
      ['t', 'Toggle light / dark theme'],
      ['d', 'Toggle compact / comfortable density'],
      ['w', 'Toggle wallboard mode'],
      ['n', 'Open the notification centre'],
    ],
  },
];

export const ShortcutsSheet: React.FC<{ isOpen: boolean; onClose: () => void }> = ({
  isOpen,
  onClose,
}) => {
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="command-palette-backdrop" onClick={onClose}>
      <div
        className="command-palette-modal"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        style={{ maxWidth: '560px' }}
      >
        <div className="palette-input-wrap" style={{ justifyContent: 'space-between' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Keyboard size={17} color="var(--its-text-accent)" />
            <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>KEYBOARD SHORTCUTS</span>
          </span>
          <button
            onClick={onClose}
            aria-label="Close shortcuts"
            style={{ background: 'transparent', border: 'none', color: 'var(--its-text-muted)', cursor: 'pointer' }}
          >
            <X size={15} />
          </button>
        </div>

        <div style={{ padding: '14px 16px', maxHeight: '60vh', overflowY: 'auto' }}>
          {SHORTCUTS.map(section => (
            <div key={section.group} style={{ marginBottom: '16px' }}>
              <div
                style={{
                  fontSize: '10px', fontWeight: 700, letterSpacing: '0.08em',
                  textTransform: 'uppercase', color: 'var(--its-text-muted)', marginBottom: '7px',
                }}
              >
                {section.group}
              </div>

              {section.items.map(([keys, description]) => (
                <div
                  key={keys}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    gap: '16px', padding: '5px 0', fontSize: 'var(--text-xs)',
                  }}
                >
                  <span style={{ color: 'var(--its-text-secondary)' }}>{description}</span>
                  <kbd className="search-shortcut-kbd" style={{ whiteSpace: 'nowrap' }}>{keys}</kbd>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
