<?php

declare(strict_types=1);

namespace Shop\Tests;

use PHPUnit\Framework\TestCase;
use Shop\Pricing;

final class PricingTest extends TestCase
{
    public function testMultipliesTheUnitPriceByTheQuantity(): void
    {
        $this->assertSame(1000, Pricing::total(250, 4));
    }
}
