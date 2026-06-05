package com.acme.order.web;

import com.acme.order.client.InventoryClient;
import com.acme.order.events.OrderCreated;
import com.acme.order.events.OrderEventPublisher;
import com.acme.order.repo.Order;
import com.acme.order.repo.OrderRepository;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {

    private final InventoryClient inventoryClient;
    private final OrderRepository orderRepository;
    private final OrderEventPublisher eventPublisher;

    public OrderController(InventoryClient inventoryClient,
                           OrderRepository orderRepository,
                           OrderEventPublisher eventPublisher) {
        this.inventoryClient = inventoryClient;
        this.orderRepository = orderRepository;
        this.eventPublisher = eventPublisher;
    }

    @PostMapping
    public OrderResponse createOrder(@RequestBody OrderRequest request) {
        inventoryClient.reserve(request.getSku(), request.getQty());
        Order order = orderRepository.save(new Order(request.getSku(), request.getQty()));
        eventPublisher.publish(new OrderCreated(order.getId()));
        return new OrderResponse(order.getId());
    }
}
