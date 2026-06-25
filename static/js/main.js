// Основные утилиты для всего приложения

function formatTime(timeStr) {
    if (!timeStr) return 'N/A';
    try {
        const dt = new Date(timeStr);
        return dt.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return timeStr;
    }
}

function formatDuration(seconds) {
    if (!seconds || seconds < 0) return '0с';
    if (seconds < 60) return seconds + 'с';
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}м ${secs}с`;
}

function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    try {
        const dt = new Date(dateStr);
        return dt.toLocaleDateString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric'
        });
    } catch {
        return dateStr;
    }
}

function getCallTypeDisplay(type) {
    const map = {
        'no_answer': '❌ Пропущенный',
        'voicemail': '📨 Голосовая почта'
    };
    return map[type] || type || 'N/A';
}

function getCallTypeClass(type) {
    const map = {
        'no_answer': 'no_answer',
        'voicemail': 'voicemail'
    };
    return map[type] || '';
}

function getStatusEmoji(status) {
    const map = {
        'ANSWERED': '✅',
        'NO ANSWER': '❌',
        'NOANSWER': '❌',
        'BUSY': '📞',
        'FAILED': '💥'
    };
    return map[status] || '❓';
}

// Debounce utility
function debounce(func, wait) {
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
