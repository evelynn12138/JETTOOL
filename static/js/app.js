// DA数据清洗业务AI应用 - 主应用JavaScript
// 通用工具函数和事件处理

class FinanceQueryApp {
    constructor() {
        this.init();
    }

    init() {
        // 全局事件监听
        this.setupGlobalEvents();

        // 初始化工具提示
        this.initTooltips();

        // 检查会话状态
        this.checkSession();
    }

    setupGlobalEvents() {
        // 全局错误处理
        window.addEventListener('error', (event) => {
            console.error('全局错误:', event.error);
            this.showError('系统发生错误，请刷新页面重试');
        });

        // 处理未捕获的Promise错误
        window.addEventListener('unhandledrejection', (event) => {
            console.error('未处理的Promise拒绝:', event.reason);
            this.showError('操作失败: ' + (event.reason?.message || '未知错误'));
        });
    }

    initTooltips() {
        // 为所有有title属性的元素添加tooltip
        const tooltips = document.querySelectorAll('[title]');
        tooltips.forEach(element => {
            element.addEventListener('mouseenter', this.showTooltip);
            element.addEventListener('mouseleave', this.hideTooltip);
        });
    }

    showTooltip(event) {
        const element = event.target;
        const title = element.getAttribute('title');

        // 创建tooltip元素
        const tooltip = document.createElement('div');
        tooltip.className = 'custom-tooltip';
        tooltip.textContent = title;

        // 设置位置
        const rect = element.getBoundingClientRect();
        tooltip.style.position = 'fixed';
        tooltip.style.left = rect.left + 'px';
        tooltip.style.top = (rect.top - 40) + 'px';
        tooltip.style.zIndex = '10000';

        // 添加样式
        tooltip.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
        tooltip.style.color = 'white';
        tooltip.style.padding = '8px 12px';
        tooltip.style.borderRadius = '4px';
        tooltip.style.fontSize = '14px';
        tooltip.style.maxWidth = '300px';
        tooltip.style.whiteSpace = 'nowrap';

        // 保存引用并显示
        element._tooltip = tooltip;
        document.body.appendChild(tooltip);

        // 清除title避免浏览器默认tooltip
        element.removeAttribute('title');
    }

    hideTooltip(event) {
        const element = event.target;
        if (element._tooltip) {
            document.body.removeChild(element._tooltip);
            element._tooltip = null;

            // 恢复title
            const tooltip = element.getAttribute('data-original-title') || element._originalTitle;
            if (tooltip) {
                element.setAttribute('title', tooltip);
            }
        }
    }

    checkSession() {
        // 检查是否有活跃的会话
        const hasSession = localStorage.getItem('hasActiveSession');
        if (hasSession) {
            this.showNotification('检测到上次未完成的会话，您可以继续操作', 'info');
        }
    }

    // 显示通知
    showNotification(message, type = 'info') {
        // 创建通知元素
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <i class="fas ${this.getNotificationIcon(type)}"></i>
                <span>${message}</span>
            </div>
            <button class="notification-close">
                <i class="fas fa-times"></i>
            </button>
        `;

        // 添加样式
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${this.getNotificationColor(type)};
            color: white;
            padding: 16px 20px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            max-width: 400px;
            z-index: 10000;
            animation: slideIn 0.3s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        `;

        // 添加动画
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideIn {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            @keyframes slideOut {
                from {
                    transform: translateX(0);
                    opacity: 1;
                }
                to {
                    transform: translateX(100%);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);

        // 关闭按钮事件
        const closeBtn = notification.querySelector('.notification-close');
        closeBtn.addEventListener('click', () => {
            notification.style.animation = 'slideOut 0.3s ease forwards';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        });

        // 自动消失
        setTimeout(() => {
            if (notification.parentNode) {
                notification.style.animation = 'slideOut 0.3s ease forwards';
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.parentNode.removeChild(notification);
                    }
                }, 300);
            }
        }, 5000);

        document.body.appendChild(notification);
    }

    getNotificationIcon(type) {
        const icons = {
            'info': 'fa-info-circle',
            'success': 'fa-check-circle',
            'warning': 'fa-exclamation-triangle',
            'error': 'fa-times-circle'
        };
        return icons[type] || 'fa-info-circle';
    }

    getNotificationColor(type) {
        const colors = {
            'info': '#3b82f6',
            'success': '#10b981',
            'warning': '#f59e0b',
            'error': '#ef4444'
        };
        return colors[type] || '#3b82f6';
    }

    // 显示错误消息
    showError(message) {
        this.showNotification(message, 'error');
    }

    // 显示成功消息
    showSuccess(message) {
        this.showNotification(message, 'success');
    }

    // 显示警告消息
    showWarning(message) {
        this.showNotification(message, 'warning');
    }

    // 显示加载状态
    showLoading(container, message = '加载中...') {
        const loading = document.createElement('div');
        loading.className = 'loading-state';
        loading.innerHTML = `
            <div class="spinner"></div>
            <p>${message}</p>
        `;

        loading.style.cssText = `
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 40px;
            text-align: center;
        `;

        const spinner = loading.querySelector('.spinner');
        spinner.style.cssText = `
            width: 40px;
            height: 40px;
            border: 3px solid #e5e7eb;
            border-top-color: #2563eb;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 16px;
        `;

        container.innerHTML = '';
        container.appendChild(loading);
        container.style.position = 'relative';
    }

    // 隐藏加载状态
    hideLoading(container) {
        const loading = container.querySelector('.loading-state');
        if (loading) {
            container.removeChild(loading);
        }
    }

    // API请求封装
    async apiRequest(url, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin'
        };

        const mergedOptions = { ...defaultOptions, ...options };

        try {
            const response = await fetch(url, mergedOptions);

            if (!response.ok) {
                throw new Error(`HTTP错误: ${response.status}`);
            }

            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            } else {
                return await response.text();
            }
        } catch (error) {
            console.error('API请求失败:', error);
            throw error;
        }
    }

    // 格式化日期
    formatDate(date, format = 'YYYY-MM-DD') {
        const d = new Date(date);
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const hours = String(d.getHours()).padStart(2, '0');
        const minutes = String(d.getMinutes()).padStart(2, '0');
        const seconds = String(d.getSeconds()).padStart(2, '0');

        return format
            .replace('YYYY', year)
            .replace('MM', month)
            .replace('DD', day)
            .replace('HH', hours)
            .replace('mm', minutes)
            .replace('ss', seconds);
    }

    // 格式化文件大小
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // 防抖函数
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    // 节流函数
    throttle(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.app = new FinanceQueryApp();
});

// 导出工具函数供其他模块使用
window.formatDate = (date, format) => {
    const app = window.app;
    return app ? app.formatDate(date, format) : '';
};

window.formatFileSize = (bytes) => {
    const app = window.app;
    return app ? app.formatFileSize(bytes) : '';
};

window.debounce = (func, wait) => {
    const app = window.app;
    return app ? app.debounce(func, wait) : null;
};

window.throttle = (func, limit) => {
    const app = window.app;
    return app ? app.throttle(func, limit) : null;
};