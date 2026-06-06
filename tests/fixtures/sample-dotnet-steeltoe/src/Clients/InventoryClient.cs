using Microsoft.Extensions.Logging;
using Polly;
using Polly.CircuitBreaker;

namespace Acme.Orders.Clients;

public class InventoryClient
{
    private readonly HttpClient _httpClient;
    private readonly AsyncCircuitBreakerPolicy _breaker;
    private readonly ILogger<InventoryClient> _logger;

    public InventoryClient(HttpClient httpClient, ILogger<InventoryClient> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
        _breaker = Policy.Handle<Exception>().CircuitBreakerAsync(5, TimeSpan.FromSeconds(30));
    }

    public async Task ReserveAsync(string sku, int qty)
    {
        await _breaker.ExecuteAsync(() => _httpClient.PostAsync($"/reserve?sku={sku}&qty={qty}", null));
    }

    public Task ReserveFallback(string sku, int qty)
    {
        _logger.LogWarning("inventory reserve fell back for sku={Sku}", sku);
        return Task.CompletedTask;
    }
}
