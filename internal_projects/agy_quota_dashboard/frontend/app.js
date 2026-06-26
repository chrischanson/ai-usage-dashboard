document.addEventListener('DOMContentLoaded', () => {
    let historyChartInstance = null;
    let modelChartInstance = null;

    Chart.defaults.color = '#94a3b8';
    Chart.defaults.font.family = "'Inter', sans-serif";

    function formatNumber(num) {
        if (num >= 1000000) return (num / 1000000).toFixed(2) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }

    async function fetchLatestData() {
        try {
            const response = await fetch('/api/usage/latest');
            const data = await response.json();
            if (Object.keys(data).length > 0) {
                updateOverview(data);
                updateModelsList(data.models);
                updateModelChart(data.models);
            }
        } catch (error) {
            console.error('Error fetching latest data:', error);
        }
    }

    async function fetchHistoryData() {
        try {
            const response = await fetch('/api/usage/history');
            const data = await response.json();
            if (data && data.length > 0) {
                updateHistoryChart(data);
            }
        } catch (error) {
            console.error('Error fetching history data:', error);
        }
    }

    function updateOverview(data) {
        document.getElementById('total-sessions').textContent = data.sessions;
        document.getElementById('total-messages').textContent = data.messages;
        document.getElementById('total-cost').textContent = '$' + data.total_cost.toFixed(2);
        document.getElementById('input-tokens').textContent = formatNumber(data.input_tokens);
        document.getElementById('output-tokens').textContent = formatNumber(data.output_tokens);
    }

    function updateModelsList(models) {
        const container = document.getElementById('models-container');
        container.innerHTML = '';

        models.forEach(model => {
            const div = document.createElement('div');
            div.className = 'model-item';
            div.innerHTML = `
                <div class="model-info">
                    <h4>${model.model_name}</h4>
                    <p>${model.messages} Messages</p>
                </div>
                <div class="model-stats">
                    <div class="tokens">${formatNumber(model.input_tokens + model.output_tokens)} Tokens</div>
                    <p>Cost: $${model.cost.toFixed(4)}</p>
                </div>
            `;
            container.appendChild(div);
        });
    }

    function updateModelChart(models) {
        const ctx = document.getElementById('modelChart').getContext('2d');
        const labels = models.map(m => m.model_name.split('/').pop());
        const data = models.map(m => m.input_tokens + m.output_tokens);

        if (modelChartInstance) {
            modelChartInstance.destroy();
        }

        modelChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: [
                        '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'
                    ],
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { padding: 20 }
                    }
                }
            }
        });
    }

    function updateHistoryChart(historyData) {
        const ctx = document.getElementById('historyChart').getContext('2d');
        const labels = historyData.map(d => {
            const date = new Date(d.timestamp);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        });
        const inputTokens = historyData.map(d => d.input_tokens);
        const outputTokens = historyData.map(d => d.output_tokens);

        if (historyChartInstance) {
            historyChartInstance.destroy();
        }

        historyChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Input Tokens',
                        data: inputTokens,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Output Tokens',
                        data: outputTokens,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        fill: true,
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                interaction: {
                    intersect: false,
                    mode: 'index',
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' }
                    },
                    x: {
                        grid: { display: false }
                    }
                }
            }
        });
    }

    // Initial fetch
    fetchLatestData();
    fetchHistoryData();

    // Poll every 60 seconds for dashboard updates
    setInterval(() => {
        fetchLatestData();
        fetchHistoryData();
    }, 60000);
});
