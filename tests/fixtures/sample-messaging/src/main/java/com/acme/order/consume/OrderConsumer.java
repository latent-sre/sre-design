package com.acme.order.consume;

import org.springframework.kafka.annotation.DltHandler;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.annotation.RetryableTopic;
import org.springframework.stereotype.Component;

@Component
public class OrderConsumer {

    private final ProcessedStore processed;

    public OrderConsumer(ProcessedStore processed) {
        this.processed = processed;
    }

    @RetryableTopic(attempts = "3")
    @KafkaListener(topics = "order.created", groupId = "orders")
    public void onOrderCreated(OrderCreated event) {
        if (processed.seen(event.idempotencyKey())) {
            return; // idempotent consumer: a replayed message is a no-op
        }
        processed.save(event.idempotencyKey());
        fulfil(event);
    }

    @DltHandler
    public void dlt(OrderCreated event) {
        // parked on the dead-letter topic for inspection
    }

    private void fulfil(OrderCreated event) {
    }
}
