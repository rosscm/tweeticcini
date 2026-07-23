document.documentElement.classList.add('js-enabled');

(function () {
  const countNodes = document.querySelectorAll('.server-count');
  const countClaims = document.querySelectorAll('.proof-primary--count');
  const fallbackClaims = document.querySelectorAll('.proof-primary--fallback');

  function showCount(count) {
    if (!Number.isFinite(count) || count <= 0) {
      return false;
    }
    countNodes.forEach(function (node) {
      node.textContent = String(count);
    });
    countClaims.forEach(function (node) {
      node.hidden = false;
      node.removeAttribute('aria-hidden');
    });
    fallbackClaims.forEach(function (node) {
      node.hidden = true;
      node.setAttribute('aria-hidden', 'true');
    });
    return true;
  }

  function showFallback() {
    countClaims.forEach(function (node) {
      node.hidden = true;
      node.setAttribute('aria-hidden', 'true');
    });
    fallbackClaims.forEach(function (node) {
      node.hidden = false;
      node.removeAttribute('aria-hidden');
    });
  }

  if (countNodes.length && countClaims.length && fallbackClaims.length) {
    showFallback();
    const cachedCount = window.localStorage.getItem('tweeticcini_server_count');
    if (cachedCount && /^\d+$/.test(cachedCount)) {
      showCount(Number(cachedCount));
    }

    fetch('https://app.tweeticcini.com/public/stats', { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) {
          return null;
        }
        return response.json();
      })
      .then(function (payload) {
        if (!payload) {
          return;
        }
        const count = Number(payload.server_count);
        if (!showCount(count)) {
          return;
        }
        window.localStorage.setItem('tweeticcini_server_count', String(count));
      })
      .catch(function () {
      });
  }
})();

(function () {
  const form = document.querySelector('[data-workflow-form]');
  if (!form) {
    return;
  }

  const preview = {
    account: document.querySelector('[data-preview-account]'),
    accountInline: document.querySelector('[data-preview-account-inline]'),
    post: document.querySelector('[data-preview-post]'),
    title: document.querySelector('[data-preview-title]'),
    keyword: document.querySelector('[data-preview-keyword]'),
    keywordInline: document.querySelector('[data-preview-keyword-inline]'),
    media: document.querySelector('[data-preview-media]'),
    mediaInline: document.querySelector('[data-preview-media-inline]'),
    channel: document.querySelector('[data-preview-channel]'),
    channelHeader: document.querySelector('[data-preview-channel-header]'),
    decision: document.querySelector('[data-preview-decision]'),
    mention: document.querySelector('[data-preview-mention]'),
    priority: document.querySelector('[data-preview-priority]'),
    style: document.querySelector('[data-preview-style]'),
    styleInline: document.querySelector('[data-preview-style-inline]'),
  };

  function getValue(name) {
    return form.elements[name].value.trim();
  }

  function render() {
    const account = getValue('account');
    const post = getValue('post');
    const keyword = getValue('keyword');
    const media = getValue('media');
    const channel = getValue('channel');
    const mention = getValue('mention');
    const priority = getValue('priority');
    const style = getValue('style');
    const mentionText = mention === 'No role' ? 'No role mention' : mention;

    preview.account.textContent = account;
    preview.accountInline.textContent = account;
    preview.post.textContent = post;
    preview.title.textContent = post;
    preview.keyword.textContent = 'Keyword: ' + keyword;
    preview.keywordInline.textContent = keyword;
    preview.media.textContent = 'Media: ' + media;
    preview.mediaInline.textContent = media;
    preview.channel.textContent = channel;
    preview.channelHeader.textContent = channel;
    preview.decision.textContent = mentionText + ' · Priority: ' + priority;
    preview.mention.textContent = mentionText;
    preview.priority.textContent = priority;
    preview.style.textContent = style;
    preview.styleInline.textContent = style;
  }

  form.addEventListener('input', render);
  form.addEventListener('change', render);
  render();
})();

(function () {
  const demo = document.querySelector('[data-tab-demo]');
  if (!demo) {
    return;
  }

  const buttons = Array.from(demo.querySelectorAll('[data-tab-target]'));
  const panels = Array.from(demo.querySelectorAll('.tab-panel'));

  function activate(targetId) {
    buttons.forEach(function (button) {
      const active = button.getAttribute('data-tab-target') === targetId;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
    });

    panels.forEach(function (panel) {
      panel.classList.toggle('is-active', panel.id === targetId);
    });
  }

  buttons.forEach(function (button, index) {
    button.addEventListener('click', function () {
      activate(button.getAttribute('data-tab-target'));
    });

    button.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') {
        return;
      }
      event.preventDefault();
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const nextIndex = (index + direction + buttons.length) % buttons.length;
      buttons[nextIndex].focus();
      activate(buttons[nextIndex].getAttribute('data-tab-target'));
    });
  });
})();
