using Microsoft.EntityFrameworkCore;

namespace Acme.Orders.Data;

public class OrdersDbContext : DbContext
{
    public DbSet<Order> Orders { get; set; }

    public Order Save(Order order)
    {
        Orders.Add(order);
        SaveChanges();
        return order;
    }
}
