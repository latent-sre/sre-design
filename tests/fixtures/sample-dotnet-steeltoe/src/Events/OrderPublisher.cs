using Confluent.Kafka;
using Microsoft.Extensions.Logging;

namespace Acme.Orders.Events;

public class OrderPublisher
{
    private readonly IProducer<string, string> _producer;
    private readonly ILogger<OrderPublisher> _logger;

    public OrderPublisher(IProducer<string, string> producer, ILogger<OrderPublisher> logger)
    {
        _producer = producer;
        _logger = logger;
    }

    public async Task PublishAsync(OrderCreated evt)
    {
        try
        {
            await _producer.ProduceAsync("orders.created",
                new Message<string, string> { Key = evt.OrderId, Value = evt.OrderId });
        }
        catch (Exception ex)
        {
            // Swallowed: the order is persisted but the event is lost. Data-loss risk.
            _logger.LogError(ex, "failed to publish orders.created event for order {OrderId}", evt.OrderId);
        }
    }
}
