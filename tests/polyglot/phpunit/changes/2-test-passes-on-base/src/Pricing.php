<?php
// Demo project, no real data.

declare(strict_types=1);

namespace Shop;

final class Pricing
{
    /** The price of an order line in cents; ten items or more get 10% off. */
    public static function total(int $unitCents, int $quantity): int
    {
        $gross = $unitCents * $quantity;
        return $quantity >= 10 ? intdiv($gross * 9, 10) : $gross;
    }
}
