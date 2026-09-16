// Generic open/close helpers reused by the date-picker modal and the losses/downtime modal.
const Modal = (() => {
  function open(overlayEl) {
    overlayEl.classList.add("open");
    const escHandler = (e) => {
      if (e.key === "Escape") close(overlayEl);
    };
    overlayEl._escHandler = escHandler;
    document.addEventListener("keydown", escHandler);
  }

  function close(overlayEl) {
    overlayEl.classList.remove("open");
    if (overlayEl._escHandler) {
      document.removeEventListener("keydown", overlayEl._escHandler);
      overlayEl._escHandler = null;
    }
  }

  function wireOverlay(overlayEl, closeBtn) {
    closeBtn.addEventListener("click", () => close(overlayEl));
    overlayEl.addEventListener("click", (e) => {
      if (e.target === overlayEl) close(overlayEl);
    });
  }

  return { open, close, wireOverlay };
})();
