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

    /** A price in cents as euros with two decimals, for example 12.50. */
    public static function formatPrice(int $cents): string
    {
        return sprintf("%d.%02d", intdiv($cents, 100), $cents % 100);
    }
}
