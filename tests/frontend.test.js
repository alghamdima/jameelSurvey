function runFrontendTests(mainSource, builderSource) {
  let assertions = 0;
  function assert(value, message) { assertions++; if (!value) throw new Error(message); }
  function setup(inputs, initial = {}, pathname = '/s/test') {
    const events = {}, saved = {...initial};
    const form = {querySelectorAll: () => inputs, addEventListener: (name, fn) => events[name] = fn};
    const document = {addEventListener: (_, fn) => fn(), getElementById: () => form};
    const sessionStorage = {
      getItem: key => saved[key] || null,
      setItem: (key, value) => saved[key] = value,
      removeItem: key => delete saved[key]
    };
    new Function('document', 'sessionStorage', 'window', mainSource)(
      document, sessionStorage, {location: {pathname}});
    return {events, saved};
  }
  const radios = [
    {type:'radio', name:'q_1', value:'opt_1', checked:false},
    {type:'radio', name:'q_1', value:'opt_2', checked:false}
  ];
  let state = setup(radios);
  radios[0].checked = true;
  state.events.change();
  assert(JSON.parse(state.saved['draft_ans_/s/test']).q_1 === 'opt_1', 'Selected radio must persist');
  const boxes = [
    {type:'checkbox', name:'q_1', value:'opt_1', checked:false},
    {type:'checkbox', name:'q_1', value:'opt_2', checked:false}
  ];
  state = setup(boxes);
  boxes[1].checked = true;
  state.events.change();
  assert(JSON.stringify(JSON.parse(state.saved['draft_ans_/s/test']).q_1) === '["opt_2"]', 'Unchecked box must not overwrite list');
  boxes[1].checked = false;
  state.events.change();
  assert(JSON.parse(state.saved['draft_ans_/s/test']).q_1.length === 0, 'Cleared checkbox must persist');
  state.events.submit();
  assert(Boolean(state.saved['draft_ans_/s/test']), 'Submission attempt must retain draft');
  const recovery = setup(radios, {'draft_ans_/s/test':'{"q_1":"opt_1"}'}, '/s/test/submit');
  assert(radios[0].checked && !radios[1].checked, 'Failed submit must restore original draft');
  const functions = ['addQuestion','removeQuestion','addOption','removeOption'].map(name =>
    builderSource.match(new RegExp('function ' + name + '\\([^]*?\\n\\}'))[0]).join('\n');
  const questions = new Function(`
    let questions = [{key:'q_1',options:[]},{key:'q_2',options:[]},
      {key:'q_3',options:[{key:'opt_1'},{key:'opt_2'},{key:'opt_3'}]}];
    function renderQuestions(){} function alert(){}
    ${functions}
    removeQuestion(1); addQuestion(); removeOption(1,1); addOption(1); return questions;
  `)();
  assert(new Set(questions.map(q=>q.key)).size === questions.length, 'Question keys must remain unique');
  assert(new Set(questions[1].options.map(o=>o.key)).size === questions[1].options.length, 'Option keys must remain unique');
  return assertions;
}
if (typeof require !== 'undefined' && typeof module !== 'undefined' && require.main === module) {
  const fs = require('node:fs'), path = require('node:path');
  const root = path.join(__dirname, '..');
  const count = runFrontendTests(fs.readFileSync(path.join(root, 'app/static/js/main.js'), 'utf8'),
    fs.readFileSync(path.join(root, 'app/templates/admin/survey_form.html'), 'utf8'));
  console.log(count + ' frontend assertions passed');
}