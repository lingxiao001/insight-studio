import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
export function useDialogFocus(active: boolean, element: RefObject<HTMLElement>, onClose: () => void, dismissible = true) {
  const close = useRef(onClose); const canDismiss = useRef(dismissible);
  close.current = onClose; canDismiss.current = dismissible;
  useEffect(() => {
    if (!active || !element.current) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const host = element.current; const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const nodes = () => [...host.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')].filter(node => node.tabIndex >= 0 && node.getAttribute('aria-hidden') !== 'true' && node.offsetParent !== null);
    const first = host.querySelector<HTMLElement>('[data-autofocus]') || nodes()[0] || host;
    first.focus({ preventScroll: true });
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && canDismiss.current) { event.preventDefault(); close.current(); }
      if (event.key === 'Tab') {
        const targets = nodes(); const start = targets[0]; const end = targets[targets.length - 1];
        if (!start) { event.preventDefault(); host.focus(); return; }
        if (event.shiftKey && (document.activeElement === start || !host.contains(document.activeElement))) { event.preventDefault(); end.focus(); }
        else if (!event.shiftKey && (document.activeElement === end || !host.contains(document.activeElement))) { event.preventDefault(); start.focus(); }
      }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener('keydown', keydown); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, [active, element]);
}
