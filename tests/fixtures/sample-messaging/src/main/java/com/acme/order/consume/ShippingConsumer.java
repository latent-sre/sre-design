package com.acme.order.consume;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class ShippingConsumer {

    // Bare listener: no @RetryableTopic/@DltHandler (a poison pill blocks the partition) and no
    // idempotency guard (a redelivery double-ships). Both are deterministic Tier-A gaps.
    @KafkaListener(topics = "order.shipped", groupId = "orders")
    public void onShipped(OrderShipped event) {
        ship(event);
    }

    private void ship(OrderShipped event) {
    }
}
