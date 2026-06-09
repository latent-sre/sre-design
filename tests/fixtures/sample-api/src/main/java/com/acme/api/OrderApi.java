package com.acme.api;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/orders")
public class OrderApi {

    @PostMapping
    public String create() {
        return "created";
    }

    @GetMapping("/{id}")
    public String get(@PathVariable String id) {
        return id;
    }

    // Not in the OpenAPI spec -> contract drift (undocumented endpoint).
    @DeleteMapping("/{id}")
    public void delete(@PathVariable String id) {
    }
}
