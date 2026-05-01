/* ============================================================================
 * Arbore Container - Runtime Branding Layer for Portainer CE 2.21.5
 * ----------------------------------------------------------------------------
 *  目标：
 *   1. 把界面上 "Portainer*" 文案替换为 "Arbore Container"
 *   2. 拦截一切对外网链接的点击跳转（不允许跳出）
 *   3. 屏蔽版本检查 / App Templates 等对外联网请求
 *   4. 用 "Arbore Container v1.0.0" 接管版本号显示
 *  说明：
 *   - 仅在前端运行时改写，不动 Portainer 二进制与 API
 *   - 通过 MutationObserver 跟随 SPA 渲染持续生效
 * ========================================================================== */
(function () {
    'use strict';

    // ------------------------------------------------------------------------
    // 配置
    // ------------------------------------------------------------------------
    var BRAND_NAME = 'Arbore Container';
    var BRAND_VERSION = '1.0.0';
    var BRAND_VERSION_LABEL = BRAND_NAME + ' v' + BRAND_VERSION;

    // 文本替换规则（按顺序，长前缀优先以避免重复替换）
    var TEXT_REPLACEMENTS = [
        [/Portainer\s+Community\s+Edition/gi, BRAND_NAME],
        [/Portainer\s+Business\s+Edition/gi, BRAND_NAME],
        [/Portainer\s+CE/gi, BRAND_NAME],
        [/Portainer\.io/gi, BRAND_NAME],
        [/Portainer/g, BRAND_NAME]
    ];

    // 需要拦截/屏蔽的外网域名关键字（命中即拒绝请求）
    var BLOCKED_HOST_KEYWORDS = [
        'portainer.io',
        'api.portainer.io',
        'updates.portainer.io',
        'update.portainer.io',
        'documentation.portainer.io',
        'docs.portainer.io',
        'github.com/portainer',
        'raw.githubusercontent.com/portainer',
        'githubusercontent.com'
    ];

    // 完全禁用的版本检查 / 模板 / 遥测 路径关键字
    var BLOCKED_PATH_KEYWORDS = [
        'updatecheck',
        'update-check',
        'templates.json',
        'analytics',
        'telemetry'
    ];

    // ------------------------------------------------------------------------
    // 工具函数
    // ------------------------------------------------------------------------
    function isExternalUrl(url) {
        if (!url) return false;
        if (typeof url !== 'string') return false;
        var lower = url.toLowerCase().trim();
        if (lower.indexOf('javascript:') === 0) return false;
        if (lower.indexOf('mailto:') === 0) return true;
        if (lower.indexOf('#') === 0) return false;
        if (lower.indexOf('/') === 0) return false;
        if (lower.indexOf('http://') !== 0 && lower.indexOf('https://') !== 0) return false;
        try {
            var u = new URL(url, window.location.origin);
            return u.origin !== window.location.origin;
        } catch (e) {
            return true;
        }
    }

    function isBlockedUrl(url) {
        if (!url || typeof url !== 'string') return false;
        var lower = url.toLowerCase();
        for (var i = 0; i < BLOCKED_HOST_KEYWORDS.length; i++) {
            if (lower.indexOf(BLOCKED_HOST_KEYWORDS[i]) !== -1) return true;
        }
        for (var j = 0; j < BLOCKED_PATH_KEYWORDS.length; j++) {
            if (lower.indexOf(BLOCKED_PATH_KEYWORDS[j]) !== -1) return true;
        }
        return false;
    }

    function applyTextReplacements(text) {
        if (!text) return text;
        var out = text;
        for (var i = 0; i < TEXT_REPLACEMENTS.length; i++) {
            out = out.replace(TEXT_REPLACEMENTS[i][0], TEXT_REPLACEMENTS[i][1]);
        }
        return out;
    }

    // ------------------------------------------------------------------------
    // 1. 拦截 fetch（屏蔽外网请求与版本检查）
    // ------------------------------------------------------------------------
    if (typeof window.fetch === 'function') {
        var origFetch = window.fetch.bind(window);
        window.fetch = function (input, init) {
            try {
                var url = typeof input === 'string' ? input : (input && input.url) || '';
                if (isBlockedUrl(url)) {
                    // 返回空响应，避免页面报错
                    return Promise.resolve(new Response('{}', {
                        status: 204,
                        headers: { 'Content-Type': 'application/json' }
                    }));
                }
            } catch (e) { /* ignore */ }
            return origFetch(input, init);
        };
    }

    // ------------------------------------------------------------------------
    // 2. 拦截 XMLHttpRequest（同样屏蔽）
    // ------------------------------------------------------------------------
    (function () {
        var origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function (method, url) {
            try {
                if (isBlockedUrl(url)) {
                    // 重定向到一个不存在的相对路径，让请求失败但不联网
                    arguments[1] = 'about:blank';
                    this.__arbore_blocked = true;
                }
            } catch (e) { /* ignore */ }
            return origOpen.apply(this, arguments);
        };
    })();

    // ------------------------------------------------------------------------
    // 3. 拦截 window.open（防止打开新窗口外链）
    // ------------------------------------------------------------------------
    var origOpen = window.open;
    window.open = function (url) {
        if (isExternalUrl(url) || isBlockedUrl(url)) {
            return null;
        }
        return origOpen.apply(window, arguments);
    };

    // ------------------------------------------------------------------------
    // 4. 全局点击拦截：阻止任何外链的跳转
    // ------------------------------------------------------------------------
    document.addEventListener('click', function (ev) {
        var node = ev.target;
        // 向上找 <a>
        while (node && node !== document.body) {
            if (node.tagName === 'A') {
                var href = node.getAttribute('href') || '';
                if (isExternalUrl(href) || isBlockedUrl(href)) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    return false;
                }
                // 移除可能的新窗口属性
                if (node.getAttribute('target') === '_blank') {
                    node.removeAttribute('target');
                }
                break;
            }
            node = node.parentNode;
        }
    }, true);

    // ------------------------------------------------------------------------
    // 5. 改写所有 <a> 元素：外链全部置为 javascript:void(0)
    //    + 去掉 target=_blank
    // ------------------------------------------------------------------------
    function neutralizeLinks(root) {
        if (!root || !root.querySelectorAll) return;
        var anchors = root.querySelectorAll('a[href]');
        for (var i = 0; i < anchors.length; i++) {
            var a = anchors[i];
            var href = a.getAttribute('href') || '';
            if (isExternalUrl(href) || isBlockedUrl(href)) {
                a.setAttribute('data-arbore-blocked-href', href);
                a.setAttribute('href', 'javascript:void(0)');
                a.style.cursor = 'default';
                a.style.textDecoration = 'none';
                a.removeAttribute('target');
            }
        }
    }

    // ------------------------------------------------------------------------
    // 6. 文本节点品牌化（只动 textNode，不改 DOM 结构，避免破坏事件绑定）
    // ------------------------------------------------------------------------
    function rebrandTextNodes(root) {
        if (!root) return;
        var walker = document.createTreeWalker(
            root,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: function (n) {
                    if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
                    if (!/Portainer/i.test(n.nodeValue)) return NodeFilter.FILTER_REJECT;
                    var p = n.parentNode;
                    if (!p) return NodeFilter.FILTER_REJECT;
                    var tag = (p.tagName || '').toLowerCase();
                    if (tag === 'script' || tag === 'style') return NodeFilter.FILTER_REJECT;
                    return NodeFilter.FILTER_ACCEPT;
                }
            },
            false
        );
        var node;
        while ((node = walker.nextNode())) {
            var newVal = applyTextReplacements(node.nodeValue);
            if (newVal !== node.nodeValue) node.nodeValue = newVal;
        }
    }

    // ------------------------------------------------------------------------
    // 7. 接管版本号显示
    //    Portainer 在多处显示 "Portainer X.Y.Z" 或单独显示版本号
    //    我们的策略：把任何包含 Portainer 版本号格式的文本统一替换
    // ------------------------------------------------------------------------
    function rebrandVersion(root) {
        if (!root || !root.querySelectorAll) return;
        // 常见版本号 DOM 位置：底部、Help/About、Settings 顶部
        // 通用：找到所有文本节点中包含语义化版本号或 "CE 2.x.x" 的进行替换
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
        var node;
        while ((node = walker.nextNode())) {
            if (!node.nodeValue) continue;
            var v = node.nodeValue;
            // "Portainer Community Edition 2.21.5" / "Portainer CE 2.21.5" / "v2.21.5"
            var re1 = /(Arbore Container|Portainer)\s*(Community Edition|CE|Business Edition|BE)?\s*[vV]?\d+\.\d+\.\d+(?:-[\w.]+)?/g;
            if (re1.test(v)) {
                node.nodeValue = v.replace(re1, BRAND_VERSION_LABEL);
                continue;
            }
            // 单独的 "v2.21.5" / "2.21.5"（仅在父元素是版本相关 class 时替换，避免误伤）
            var p = node.parentElement;
            if (p) {
                var cls = (p.className || '').toString().toLowerCase();
                var id = (p.id || '').toString().toLowerCase();
                if (
                    /version|footer|about|build/.test(cls) ||
                    /version|footer|about|build/.test(id)
                ) {
                    var re2 = /[vV]?\d+\.\d+\.\d+(?:-[\w.]+)?/g;
                    if (re2.test(v)) {
                        node.nodeValue = v.replace(re2, 'v' + BRAND_VERSION);
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------------
    // 8. 隐藏明确的"对外引流" UI 元素（用 CSS）
    //    无法替换 logo 仅按用户要求；其他外链按钮 / 业务版升级 / 新版本提示等隐藏
    // ------------------------------------------------------------------------
    function injectBrandingCss() {
        if (document.getElementById('arbore-branding-style')) return;
        var css = [
            // 顶栏 "Upgrade to Business Edition" 区域
            '[class*="be-indicator"], [class*="upgrade-be"], [class*="upgrade_be"],',
            '[class*="be-banner"], [class*="business-banner"],',
            '[class*="UpgradeBE"], [class*="upgradeBE"],',
            'a[href*="portainer.io/upgrade"], a[href*="portainer.io/business"],',
            'a[href*="portainer.io/take-3min"], a[href*="portainer.io/why-upgrade"]',
            '{ display: none !important; visibility: hidden !important; }',
            // 左下 "New version available" / "See what\'s new" 提示卡
            '[class*="new-version"], [class*="newVersion"], [class*="update-notification"],',
            '[class*="version-notification"], [class*="whats-new"], [class*="WhatsNew"]',
            '{ display: none !important; }',
            // 底部 portainer.io logo 链接（左下浅色那块）
            'a[href*="portainer.io"], a[href*="api.portainer.io"], a[href*="updates.portainer.io"]',
            '{ pointer-events: none !important; cursor: default !important; }',
            // 通用：被我们标记过的外链一律不响应
            'a[data-arbore-blocked-href]',
            '{ pointer-events: none !important; cursor: default !important; text-decoration: none !important; color: inherit !important; }'
        ].join('\n');
        var style = document.createElement('style');
        style.id = 'arbore-branding-style';
        style.type = 'text/css';
        style.appendChild(document.createTextNode(css));
        (document.head || document.documentElement).appendChild(style);
    }

    // ------------------------------------------------------------------------
    // 9. 主流程：初始化 + MutationObserver
    // ------------------------------------------------------------------------
    function applyAll(root) {
        try { neutralizeLinks(root); } catch (e) { /* noop */ }
        try { rebrandTextNodes(root); } catch (e) { /* noop */ }
        try { rebrandVersion(root); } catch (e) { /* noop */ }
    }

    function bootstrap() {
        injectBrandingCss();
        applyAll(document.body || document.documentElement);

        try { document.title = BRAND_NAME; } catch (e) { /* noop */ }

        var observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var m = mutations[i];
                if (m.type === 'childList') {
                    for (var j = 0; j < m.addedNodes.length; j++) {
                        var n = m.addedNodes[j];
                        if (n.nodeType === 1) {
                            applyAll(n);
                        } else if (n.nodeType === 3 && /Portainer/i.test(n.nodeValue || '')) {
                            n.nodeValue = applyTextReplacements(n.nodeValue);
                        }
                    }
                } else if (m.type === 'characterData' && m.target && /Portainer/i.test(m.target.nodeValue || '')) {
                    m.target.nodeValue = applyTextReplacements(m.target.nodeValue);
                } else if (m.type === 'attributes' && m.attributeName === 'href') {
                    if (m.target && m.target.tagName === 'A') {
                        var href = m.target.getAttribute('href') || '';
                        if (isExternalUrl(href) || isBlockedUrl(href)) {
                            m.target.setAttribute('data-arbore-blocked-href', href);
                            m.target.setAttribute('href', 'javascript:void(0)');
                            m.target.removeAttribute('target');
                        }
                    }
                }
            }
        });
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: ['href', 'target']
        });

        // 为防 SPA 第一次 render 还没完成，再补几次
        var ticks = 0;
        var tickTimer = setInterval(function () {
            ticks++;
            applyAll(document.body || document.documentElement);
            if (ticks >= 10) clearInterval(tickTimer);
        }, 500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }
})();
