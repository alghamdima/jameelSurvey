/**
 * سكريبت الواجهة الأمامية - JavaScript خفيف وموثوق
 * يدعم التفاعل مع واجهة المستخدم، إدارة التركيز، وحفظ حالة الحقول عند تبديل اللغة.
 */

document.addEventListener('DOMContentLoaded', () => {
  // حفظ قيم الحقول المدخلة في sessionStorage لتجنب مسحها عند تبديل اللغة
  const surveyForm = document.getElementById('survey-submit-form');
  if (surveyForm) {
    const inputs = surveyForm.querySelectorAll('input, textarea');
    const storageKey = `draft_ans_${window.location.pathname}`;

    // استعادة الإجابات المحفوظة مسبقاً إذا وُجدت
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved) {
        const data = JSON.parse(saved);
        inputs.forEach(input => {
          if (input.type === 'radio') {
            if (data[input.name] === input.value) input.checked = true;
          } else if (input.type === 'checkbox') {
            if (Array.isArray(data[input.name]) && data[input.name].includes(input.value)) {
              input.checked = true;
            }
          } else if (input.type !== 'hidden' && data[input.name]) {
            input.value = data[input.name];
          }
        });
      }
    } catch (e) {
      // تجاهل أخطاء التخزين المحلي إن وُجدت
    }

    // حفظ التغييرات فور إدخالها
    surveyForm.addEventListener('change', () => {
      const currentData = {};
      inputs.forEach(input => {
        if (input.type === 'radio' && input.checked) {
          currentData[input.name] = input.value;
        } else if (input.type === 'checkbox' && input.checked) {
          currentData[input.name] = currentData[input.name] || [];
          currentData[input.name].push(input.value);
        } else if (input.type !== 'hidden' && input.value) {
          currentData[input.name] = input.value;
        }
      });
      sessionStorage.setItem(storageKey, JSON.stringify(currentData));
    });

    // مسح المسودة المؤقتة عند الإرسال النهائي الناجح
    surveyForm.addEventListener('submit', () => {
      sessionStorage.removeItem(storageKey);
    });
  }
});
