document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('survey-submit-form');
  if (!form) return;
  const inputs = form.querySelectorAll('input, textarea');
  const storageKey = 'draft_ans_' + window.location.pathname.replace(/\/submit$/, '');
  try {
    const data = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    inputs.forEach(input => {
      if (input.type === 'radio') {
        input.checked = data[input.name] === input.value;
      } else if (input.type === 'checkbox') {
        input.checked = Array.isArray(data[input.name]) && data[input.name].includes(input.value);
      } else if (input.type !== 'hidden' && typeof data[input.name] === 'string') {
        input.value = data[input.name];
      }
    });
  } catch (_) {}
  function saveDraft() {
    const data = Object.create(null);
    inputs.forEach(input => {
      if (!input.name || input.type === 'hidden') return;
      if (input.type === 'radio') {
        if (input.checked) data[input.name] = input.value;
      } else if (input.type === 'checkbox') {
        if (!data[input.name]) data[input.name] = [];
        if (input.checked) data[input.name].push(input.value);
      } else {
        data[input.name] = input.value;
      }
    });
    try { sessionStorage.setItem(storageKey, JSON.stringify(data)); } catch (_) {}
  }
  form.addEventListener('input', saveDraft);
  form.addEventListener('change', saveDraft);
  form.addEventListener('submit', saveDraft);
  // Clear only on the server-confirmed thank-you page.
});