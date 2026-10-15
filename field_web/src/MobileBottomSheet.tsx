import { useEffect, useId, useRef, type ReactNode } from "react";

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}

/** Mobile field-map modal. The map stays mounted and becomes inert underneath. */
export function MobileBottomSheet({ title, onClose, children, footer }: Props) {
  const titleId = useId();
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const dialog = dialogRef.current;
    const backdrop = backdropRef.current;
    if (!dialog || !backdrop) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const siblings = new Map<Element, { inert: string | null; hidden: string | null }>();
    const protectBackground = () => {
      Array.from(backdrop.parentElement?.children ?? []).forEach((element) => {
        if (element === backdrop || siblings.has(element)) return;
        siblings.set(element, { inert: element.getAttribute("inert"), hidden: element.getAttribute("aria-hidden") });
        element.setAttribute("inert", "");
        element.setAttribute("aria-hidden", "true");
      });
    };
    // Move focus before hiding the previously focused header from accessibility APIs.
    dialog.querySelector<HTMLButtonElement>("button")?.focus();
    protectBackground();
    // A refreshed snapshot may add an error banner while the dialog is open.
    const observer = new MutationObserver(protectBackground);
    if (backdrop.parentElement) observer.observe(backdrop.parentElement, { childList: true });
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      "button, a, input, select, textarea, [tabindex]",
    )).filter((element) => element.tabIndex >= 0 && !element.matches(':disabled, input[type="hidden"]')
      && !element.closest("[hidden], [inert]"));
    const focusInside = () => (focusable()[0] ?? dialog).focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current();
      } else if (event.key === "Tab") {
        const elements = focusable();
        const first = elements[0];
        const last = elements.at(-1);
        if (!first || !last) { event.preventDefault(); dialog.focus(); return; }
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
          event.preventDefault(); first.focus();
        }
      }
    };
    const onFocus = (event: FocusEvent) => {
      if (!dialog.contains(event.target as Node)) focusInside();
    };
    window.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocus);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocus);
      observer.disconnect();
      siblings.forEach(({ inert, hidden }, element) => {
        if (inert === null) element.removeAttribute("inert"); else element.setAttribute("inert", inert);
        if (hidden === null) element.removeAttribute("aria-hidden"); else element.setAttribute("aria-hidden", hidden);
      });
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  return (
    <div ref={backdropRef} className="mobile-sheet-backdrop" onClick={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section ref={dialogRef} className="mobile-bottom-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="mobile-sheet-heading">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="mobile-icon-button" onClick={onClose} aria-label={`${title} 닫기`}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
          </button>
        </div>
        <div className="mobile-sheet-body">{children}</div>
        {footer && <div className="mobile-sheet-footer">{footer}</div>}
      </section>
    </div>
  );
}
