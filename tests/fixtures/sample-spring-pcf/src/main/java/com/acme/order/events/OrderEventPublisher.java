package com.acme.order.events;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class OrderEventPublisher {

    private static final Logger log = LoggerFactory.getLogger(OrderEventPublisher.class);

    private final KafkaTemplate<String, OrderCreated> kafkaTemplate;

    public OrderEventPublisher(KafkaTemplate<String, OrderCreated> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    public void publish(OrderCreated event) {
        try {
            kafkaTemplate.send("order.created", event.getOrderId(), event);
        } catch (Exception e) {
            // Swallowed: the order is persisted but the event is lost. Data-loss risk.
            log.error("failed to publish order.created event for order {}", event.getOrderId(), e);
        }
    }
}
