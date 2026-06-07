package com.acme.checkout.client;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.timelimiter.annotation.TimeLimiter;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class ShippingClient {

    private final RestTemplate restTemplate;
    private final String baseUrl;

    public ShippingClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl;
    }

    // CONTROL: this remote call DOES carry a timeout (@TimeLimiter). A gap proposed here is
    // false, and the engine's signature-based refutation probe must drop it.
    @CircuitBreaker(name = "shipping", fallbackMethod = "quoteFallback")
    @TimeLimiter(name = "shipping")
    public Quote quote(String orderId) {
        return restTemplate.getForObject(baseUrl + "/quote?order=" + orderId, Quote.class);
    }

    private Quote quoteFallback(String orderId, Throwable t) {
        return Quote.unavailable(orderId);
    }
}
