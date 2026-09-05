// synchronization-map: section=web-client; role=ui-help-primitive; boundaries=web-client; doc=docs/SYNCHRONIZATION_MAP.md
/**
 * Long-press-to-explain.
 *
 * Wrap any single interactive element in <Explain text="...">. On a long press
 * (touch or mouse) a shared bottom sheet slides up with the explanation, and
 * the press does NOT also fire the element's normal onClick. A short tap/click
 * behaves exactly as before.
 *
 * Rationale: many CastCast controls (pre-flight, remaster, DRM, discovery) are
 * conceptually dense. Rather than crowd the terminal-green UI with helper copy,
 * every control carries its own explanation one long-press away.
 */

import {
  cloneElement,
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { HelpCircle, X } from "lucide-react";

const LONG_PRESS_MS = 450;
const MOVE_CANCEL_PX = 10;

interface HelpContextValue {
  show: (title: string, text: string) => void;
}

const HelpContext = createContext<HelpContextValue | null>(null);

export function LongPressHelpProvider({ children }: { children: ReactNode }) {
  const [entry, setEntry] = useState<{ title: string; text: string } | null>(null);

  const show = useCallback((title: string, text: string) => {
    setEntry({ title, text });
    // A short buzz confirms the gesture registered on devices that support it.
    try {
      navigator.vibrate?.(15);
    } catch {
      /* vibration unsupported; ignore */
    }
  }, []);

  const value = useMemo(() => ({ show }), [show]);

  return (
    <HelpContext.Provider value={value}>
      {children}
      {entry && (
        <div
          className="fixed inset-0 z-[60] flex items-end justify-center bg-black/70 p-4 backdrop-blur-sm"
          onClick={() => setEntry(null)}
        >
          <div
            className="w-full max-w-md rounded-t-xl rounded-b-md border border-emerald-500/40 bg-[#0a100d] p-5 shadow-[0_0_30px_rgba(16,185,129,0.15)]"
            style={{ fontFamily: "'Exo 2', sans-serif" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-emerald-400">
                <HelpCircle className="h-5 w-5" />
                <h2 className="tracking-wide">{entry.title}</h2>
              </div>
              <button
                onClick={() => setEntry(null)}
                className="text-emerald-500/60 hover:text-emerald-300"
                aria-label="close explanation"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="text-sm leading-relaxed text-emerald-100/80">{entry.text}</p>
          </div>
        </div>
      )}
    </HelpContext.Provider>
  );
}

export function useExplain(): HelpContextValue {
  const ctx = useContext(HelpContext);
  // Degrade gracefully if used outside a provider: no-op rather than crash.
  return ctx ?? { show: () => undefined };
}

interface ExplainProps {
  /** Short explanation shown on long-press. */
  text: string;
  /** Optional sheet heading; defaults to "What is this?". */
  title?: string;
  children: ReactElement;
}

/**
 * Attaches long-press handlers to its single child element without changing
 * layout (uses cloneElement rather than an extra wrapper node). The child must
 * be a single DOM/element node that accepts pointer + click handlers.
 */
export function Explain({ text, title = "What is this?", children }: ExplainProps) {
  const { show } = useExplain();
  const timer = useRef<number | null>(null);
  const firedRef = useRef(false);
  const startRef = useRef<{ x: number; y: number } | null>(null);

  const clear = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    startRef.current = null;
  }, []);

  if (!isValidElement(children)) return children;

  const child = children as ReactElement<any>;
  const childProps = child.props as Record<string, any>;

  const handlePointerDown = (e: React.PointerEvent) => {
    firedRef.current = false;
    startRef.current = { x: e.clientX, y: e.clientY };
    clear();
    timer.current = window.setTimeout(() => {
      firedRef.current = true;
      show(title, text);
    }, LONG_PRESS_MS);
    childProps.onPointerDown?.(e);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    const start = startRef.current;
    if (start) {
      const dx = Math.abs(e.clientX - start.x);
      const dy = Math.abs(e.clientY - start.y);
      if (dx > MOVE_CANCEL_PX || dy > MOVE_CANCEL_PX) clear();
    }
    childProps.onPointerMove?.(e);
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    clear();
    childProps.onPointerUp?.(e);
  };

  const handlePointerLeave = (e: React.PointerEvent) => {
    clear();
    childProps.onPointerLeave?.(e);
  };

  const handlePointerCancel = (e: React.PointerEvent) => {
    clear();
    childProps.onPointerCancel?.(e);
  };

  const handleClick = (e: React.MouseEvent) => {
    // If a long-press just fired, swallow the trailing click so the control's
    // real action does not run.
    if (firedRef.current) {
      firedRef.current = false;
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    childProps.onClick?.(e);
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    // Suppress the desktop right-click / touch-hold context menu when our
    // long-press has taken over.
    if (firedRef.current) e.preventDefault();
    childProps.onContextMenu?.(e);
  };

  return cloneElement(child, {
    onPointerDown: handlePointerDown,
    onPointerMove: handlePointerMove,
    onPointerUp: handlePointerUp,
    onPointerLeave: handlePointerLeave,
    onPointerCancel: handlePointerCancel,
    onClick: handleClick,
    onContextMenu: handleContextMenu,
    // Keep the desktop-hover tooltip as a secondary affordance.
    title: childProps.title ?? text,
  });
}
