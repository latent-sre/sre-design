package com.acme.order.client;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.timelimiter.annotation.TimeLimiter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class InventoryClient {

    private static final Logger log = LoggerFactory.getLogger(InventoryClient.class);

    private final RestTemplate restTemplate;
    private final String baseUrl;

    public InventoryClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl;
    }

    @CircuitBreaker(name = "inventory", fallbackMethod = "reserveFallback")
    @TimeLimiter(name = "inventory")
    public void reserve(String sku, int qty) {
        restTemplate.postForObject(baseUrl + "/reserve?sku=" + sku + "&qty=" + qty, null, Void.class);
    }

    private void reserveFallback(String sku, int qty, Throwable t) {
        log.warn("inventory reserve fell back for sku={} qty={}", sku, qty, t);
    }
}
