using Acme.Orders.Clients;
using Acme.Orders.Data;
using Acme.Orders.Events;
using Microsoft.AspNetCore.Mvc;

namespace Acme.Orders.Controllers;

[ApiController]
[Route("api/v1/orders")]
public class OrdersController : ControllerBase
{
    private readonly InventoryClient _inventory;
    private readonly OrdersDbContext _db;
    private readonly OrderPublisher _publisher;

    public OrdersController(InventoryClient inventory, OrdersDbContext db, OrderPublisher publisher)
    {
        _inventory = inventory;
        _db = db;
        _publisher = publisher;
    }

    [HttpPost]
    public async Task<OrderResponse> CreateOrder([FromBody] OrderRequest request)
    {
        await _inventory.ReserveAsync(request.Sku, request.Qty);
        var order = _db.Save(new Order(request.Sku, request.Qty));
        await _publisher.PublishAsync(new OrderCreated(order.Id));
        return new OrderResponse(order.Id);
    }
}
