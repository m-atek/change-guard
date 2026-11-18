<?php
// Demo project, no real data.

declare(strict_types=1);

namespace Shop;

final class Pricing
{
    /** The price of an order line in cents. */
    public static function total(int $unitCents, int $quantity): int
    {
        return $unitCents * $quantity;
    }
}
