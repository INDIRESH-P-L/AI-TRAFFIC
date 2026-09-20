import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  Activity,
  Map,
  GitCommit,
  Sliders,
  AlertTriangle,
  Bot,
  Settings,
  CornerDownLeft,
  X
} from 'lucide-react';
import { api } from '../api/client';

interface PaletteItem {
  id: string;
  title: string;
  subtitle: string;
  category: 'NAVIGATION' | 'INTERSECTION' | 'CONTROLLER' | 'INCIDENT';
  path: string;
  icon: React.ReactNode;
}

const STATIC_ROUTES: PaletteItem[] = [
  { id: 'nav-dash', title: 'Dashboard', subtitle: 'Real-time operational network overview & GIS map', category: 'NAVIGATION', path: '/dashboard', icon: <Activity size={16} /> },
  { id: 'nav-map', title: 'Live GIS Operations Map', subtitle: 'Full-scale spatial network monitoring', category: 'NAVIGATION', path: '/live-map', icon: <Map size={16} /> },
  { id: 'nav-intersections', title: 'Intersections & Signals', subtitle: '4-way topologies, NEMA TS2 controllers & timing', category: 'NAVIGATION', path: '/intersections', icon: <Sliders size={16} /> },
  { id: 'nav-incidents', title: 'Incident Command Console', subtitle: 'Active roadway blockages, triage & clearance', category: 'NAVIGATION', path: '/incidents', icon: <AlertTriangle size={16} /> },
  { id: 'nav-copilot', title: 'AI Operations Copilot', subtitle: 'Grounded MUTCD 4D query assistant & analytics', category: 'NAVIGATION', path: '/ai-copilot', icon: <Bot size={16} /> },
  { id: 'nav-settings', title: 'System Settings & Health', subtitle: 'Hardware reachability wizards & system config', category: 'NAVIGATION', path: '/settings', icon: <Settings size={16} /> },
];

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [dynamicItems, setDynamicItems] = useState<PaletteItem[]>([]);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);

      // Fetch actual backend entities for instant search
      Promise.all([
        api.getIntersections().catch(() => []),
        api.getControllers().catch(() => []),
        api.getIncidents().catch(() => [])
      ]).then(([intersections, controllers, incidents]) => {
        const items: PaletteItem[] = [];

        intersections.forEach((item: any) => {
          items.push({
            id: `int-${item.id}`,
            title: item.name,
            subtitle: `Intersection • ${item.control_type || 'NEMA TS2'} • ${item.latitude?.toFixed(4)}, ${item.longitude?.toFixed(4)}`,
            category: 'INTERSECTION',
            path: `/intersections/${item.id}`,
            icon: <GitCommit size={16} color="#38bdf8" />
          });
        });

        controllers.forEach((ctrl: any) => {
          items.push({
            id: `ctrl-${ctrl.id}`,
            title: `${ctrl.name} (${ctrl.ip_address || 'Unset IP'})`,
            subtitle: `Controller • ${ctrl.make_model || 'NEMA TS2'} • ${ctrl.connection_status}`,
            category: 'CONTROLLER',
            path: '/signals',
            icon: <Sliders size={16} color="#10b981" />
          });
        });

        incidents.forEach((inc: any) => {
          items.push({
            id: `inc-${inc.id}`,
            title: inc.title,
            subtitle: `Incident • ${inc.severity} • ${inc.status}`,
            category: 'INCIDENT',
            path: '/incidents',
            icon: <AlertTriangle size={16} color="#ef4444" />
          });
        });

        setDynamicItems(items);
      });
    }
  }, [isOpen]);

  // Combine and filter results
  const allItems = [...STATIC_ROUTES, ...dynamicItems];
  const filteredItems = query.trim() === ''
    ? STATIC_ROUTES
    : allItems.filter(item =>
        item.title.toLowerCase().includes(query.toLowerCase()) ||
        item.subtitle.toLowerCase().includes(query.toLowerCase()) ||
        item.category.toLowerCase().includes(query.toLowerCase())
      );

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex(prev => (prev + 1) % (filteredItems.length || 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(prev => (prev - 1 + filteredItems.length) % (filteredItems.length || 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredItems[selectedIndex]) {
          navigate(filteredItems[selectedIndex].path);
          onClose();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, filteredItems, selectedIndex, navigate, onClose]);

  if (!isOpen) return null;

  return (
    <div className="command-palette-backdrop" onClick={onClose}>
      <div className="command-palette-modal" onClick={e => e.stopPropagation()}>
        <div className="palette-input-wrap">
          <Search size={18} color="var(--its-text-accent)" />
          <input
            ref={inputRef}
            type="text"
            className="palette-input"
            placeholder="Search intersections, controllers, incidents, or commands..."
            value={query}
            onChange={e => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
          />
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--its-text-muted)',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div className="palette-results">
          {filteredItems.length === 0 ? (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--its-text-muted)', fontSize: 'var(--text-xs)' }}>
              No entities or commands match "{query}".
            </div>
          ) : (
            filteredItems.map((item, idx) => (
              <div
                key={item.id}
                className={`palette-item ${idx === selectedIndex ? 'selected' : ''}`}
                onMouseEnter={() => setSelectedIndex(idx)}
                onClick={() => {
                  navigate(item.path);
                  onClose();
                }}
              >
                <div className="palette-item-left">
                  {item.icon}
                  <div>
                    <div className="palette-item-title">{item.title}</div>
                    <div className="palette-item-subtitle">{item.subtitle}</div>
                  </div>
                </div>
                <div className="palette-item-badge">{item.category}</div>
              </div>
            ))
          )}
        </div>

        <div className="palette-footer">
          <span>Navigate with <kbd className="search-shortcut-kbd">↑</kbd> <kbd className="search-shortcut-kbd">↓</kbd></span>
          <span>Select <kbd className="search-shortcut-kbd"><CornerDownLeft size={10} style={{ display: 'inline' }} /> ENTER</kbd></span>
          <span>Close <kbd className="search-shortcut-kbd">ESC</kbd></span>
        </div>
      </div>
    </div>
  );
};
